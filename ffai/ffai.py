#!/usr/bin/env python3
"""
ffai.py

A CLI wrapper that uses a Pydantic-AI agent to PLAN and then EXECUTE ffmpeg workflows.

Usage examples:
  ffai "convert input.mov to mp4 suitable for youtube"
  ffai -y "compress input.mp4 by 10x"

Features:
- Two-phase flow: (1) model produces a structured Plan (Pydantic), (2) user approves, (3) steps executed.
- After each step we report results back to the model so it can re-plan or verify ("daisy-chaining").
- A single tool `run_ffmpeg` runs ffmpeg via subprocess and returns structured output to the agent when used.

Notes:
- Requires Python packages: pydantic, pydantic-ai (or adjust to your LLM stack), rich (optional for nicer CLI)
- Requires ffmpeg (and ffprobe for duration/metadata) available in PATH.

Security: this script executes arbitrary ffmpeg commands derived from the model. Use in trusted environments only.
"""

from __future__ import annotations
import argparse
import json
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
from dotenv import load_dotenv

load_dotenv()

try:
    from pydantic import BaseModel, Field
except Exception:
    print("Please install 'pydantic' (pip install pydantic)")
    raise

# pydantic-ai is optional for those who have it; we provide fallbacks if missing.
try:
    from pydantic_ai import Agent, RunContext
    HAVE_PYDANTIC_AI = True
except Exception:
    HAVE_PYDANTIC_AI = False

# Optional niceties
try:
    from rich import print as rprint
    from rich.panel import Panel
    from rich.table import Table
except Exception:
    rprint = print


# ----------------------------- Pydantic models -----------------------------
class Step(BaseModel):
    idx: int
    description: str
    command: List[str]  # ffmpeg command as argv list
    input: Optional[str] = None
    output: Optional[str] = None
    note: Optional[str] = None


class Plan(BaseModel):
    summary: str
    steps: List[Step]
    final_output: Optional[str]


class FFResult(BaseModel):
    step_idx: int
    command: List[str]
    returncode: int
    stdout: str
    stderr: str
    output_path: Optional[str]
    output_size: Optional[int]


# ------------------------------- Utilities --------------------------------

def ensure_ffmpeg():
    if shutil.which("ffmpeg") is None:
        rprint("[red]Error:[/red] ffmpeg not found in PATH. Install ffmpeg and try again.")
        sys.exit(2)
    if shutil.which("ffprobe") is None:
        rprint("[yellow]Warning:[/yellow] ffprobe not found in PATH. Duration/metadata checks will be limited.")


def safe_path(p: str) -> Path:
    pth = Path(p).expanduser()
    if not pth.exists():
        raise FileNotFoundError(f"Path not found: {pth}")
    # Resolve but don't allow paths that traverse out of a sane root? Keep it minimal.
    return pth.resolve()


def run_subprocess(cmd: List[str], cwd: Optional[Path] = None, timeout: Optional[int] = None) -> subprocess.CompletedProcess:
    # We intentionally don't use shell=True. We capture output.
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd, timeout=timeout, text=True)


def human_size(n: Optional[int]) -> str:
    if n is None:
        return "?"
    for unit in ["B", "KB", "MB", "GB"]:
        if n < 1024.0:
            return f"{n:.1f}{unit}"
        n /= 1024.0
    return f"{n:.1f}TB"


# ------------------------------- Tools / Agent -----------------------------
# If pydantic-ai is present, register run_ffmpeg as a tool callable by the model.


def run_ffmpeg_tool_impl(ctx, input_path: str, args: List[str], output: Optional[str] = None) -> dict:
    """
    Runs ffmpeg with given args. `args` should be a list of ffmpeg CLI args excluding the leading 'ffmpeg'.
    Example: args=['-i', 'in.mp4', '-c:v','libx264','out.mp4']
    Returns a dict that can be fed back to the model.
    """
    ensure_ffmpeg()
    in_path = Path(input_path)
    if not in_path.exists():
        return {"error": f"input {input_path} not found"}

    if output is None:
        # produce a sane output filename next to input
        output = str(in_path.with_suffix('.out' + in_path.suffix))

    cmd = ["ffmpeg", "-y"] + args
    # If the command doesn't include input and output explicitly, this will run as-is. We trust the model to provide full args.
    proc = run_subprocess(cmd)

    out_size = None
    out_path = Path(output) if Path(output).exists() else None
    if out_path and out_path.exists():
        out_size = out_path.stat().st_size

    result = {
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "output_path": str(out_path) if out_path else None,
        "output_size": out_size,
    }
    return result


# ------------------------------ Main logic --------------------------------

def build_plan_with_agent(prompt: str, model: str = "openrouter:moonshotai/kimi-k2-thinking") -> Plan:
    """
    Ask the LLM to produce a Plan. If pydantic-ai is available, use it with result_type=Plan.
    Otherwise fallback to a naive builtin planner for simple conversions.
    """
    if HAVE_PYDANTIC_AI:
        system = (
            "You are an agent that outputs a JSON plan (matching the provided Pydantic Plan schema).\n"
            "Return only valid JSON that can be parsed into the Plan model.\n"
            "Fields: summary (string), steps (list of steps). Each step must include idx, description, command (list of args), input, output.\n"
            "The commands must be safe POSIX argv lists for ffmpeg (do not inject shell).\n"
        )
        agent = Agent(model, system_prompt=system)
        run = agent.run_sync(prompt, message_history=None)
        return run.output

    # fallback simple planner: try to interpret instructions heuristically
    # Support patterns like "convert X to mp4" or "compress X by 10x"
    # This fallback is intentionally limited.
    tokens = prompt.lower().split()
    # Find first existing path-looking token in prompt
    words = prompt.split()
    input_path = None
    for w in words:
        if w.endswith(('.mp4', '.mov', '.mkv', '.avi')):
            if Path(w).exists():
                input_path = str(Path(w).resolve())
                break
    if input_path is None:
        raise ValueError("Fallback planner: couldn't infer input path. Provide a filename like 'input.mp4'.")

    if 'convert' in tokens and 'mp4' in tokens:
        out = str(Path(input_path).with_suffix('.youtube.mp4'))
        # simple yt encoding: 1080p h264 baseline
        cmd = ["-i", input_path, "-c:v", "libx264", "-preset", "medium", "-crf", "23", "-c:a", "aac", "-b:a", "192k", out]
        step = Step(idx=1, description="Convert to MP4 H.264/AAC for YouTube", command=cmd, input=input_path, output=out)
        plan = Plan(summary="Convert to MP4 for YouTube", steps=[step], final_output=out)
        return plan

    # generic compress by ratio
    if 'compress' in tokens:
        # look for 'by' and a number like '10x'
        ratio = 10
        for i, t in enumerate(tokens):
            if t.endswith('x') and t[:-1].isdigit():
                ratio = int(t[:-1])
        out = str(Path(input_path).with_name(Path(input_path).stem + f'.compressed.mp4'))
        # crude way: increase CRF by log10(ratio)
        crf = max(18, 18 + int(3 * (ratio**0.5)))
        cmd = ["-i", input_path, "-c:v", "libx264", "-preset", "slow", "-crf", str(crf), out]
        step = Step(idx=1, description=f"Compress by ~{ratio}x (crf {crf})", command=cmd, input=input_path, output=out)
        plan = Plan(summary=f"Compress {input_path} by ~{ratio}x", steps=[step], final_output=out)
        return plan

    raise ValueError("Couldn't plan the requested operation. Use a more explicit prompt like: 'convert input.mov to mp4 suitable for youtube'")


def present_plan(plan: Plan) -> None:
    rprint(Panel(f"[bold]Plan summary[/bold]\n{plan.summary}"))
    for s in plan.steps:
        t = Table(title=f"Step {s.idx}: {s.description}")
        t.add_column("field")
        t.add_column("value")
        t.add_row("command", ' '.join(shlex.quote(x) for x in s.command))
        t.add_row("input", s.input or "-")
        t.add_row("output", s.output or "-")
        rprint(t)


def confirm(prompt: str, default=False) -> bool:
    if default:
        return True
    ans = input(f"{prompt} [y/N]: ")
    return ans.strip().lower().startswith('y')


def execute_plan(plan: Plan, work_dir: Optional[Path] = None) -> List[FFResult]:
    ensure_ffmpeg()
    results: List[FFResult] = []
    if work_dir is None:
        work_dir = Path(tempfile.mkdtemp(prefix="ffai-"))
    else:
        work_dir.mkdir(parents=True, exist_ok=True)

    for step in plan.steps:
        rprint(Panel(f"Executing step {step.idx}: {step.description}"))
        # Ensure inputs exist or are absolute
        if step.input:
            inp = Path(step.input)
            if not inp.exists():
                rprint(f"[red]Input not found:[/red] {step.input}")
                # abort
                break
        # run
        cmd = ["ffmpeg", "-y"] + step.command
        rprint("\n" + " ".join(shlex.quote(x) for x in cmd))
        proc = run_subprocess(cmd, cwd=work_dir)
        out_path = None
        if step.output:
            p = Path(step.output)
            if p.exists():
                out_path = str(p.resolve())
        out_size = None
        if out_path:
            try:
                out_size = Path(out_path).stat().st_size
            except Exception:
                out_size = None

        res = FFResult(step_idx=step.idx, command=cmd, returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr, output_path=out_path, output_size=out_size)
        results.append(res)

        # show a short summary
        rprint(f"Step {step.idx} returncode={res.returncode} output={res.output_path} size={human_size(res.output_size)}")

        # After each step, give the model a chance to inspect results and re-plan (daisy-chaining):
        if HAVE_PYDANTIC_AI:
            # create a small agent to receive the step result and ask whether to continue or change
            sys_prompt = (
                "You are an execution assistant. The user asked to run the following ffmpeg workflow. "
                "You will be shown the step that just ran and its stdout/stderr and the produced output path and size. "
                "Reply with a concise JSON object: {\"action\": \"continue\" | \"replan\", \"reason\": string, \"new_steps\": optional list of steps}"
            )
            agent = Agent(model, system_prompt=sys_prompt)
            observation = {
                "step": step.dict(),
                "result": res.dict(),
            }
            prompt = f"Observation:\n{json.dumps(observation, indent=2)}\n\nBased on the observation, should execution continue? If yes reply action=continue. If not, reply action=replan and include new_steps as a list of step dicts."
            run = agent.run_sync(prompt, timeout=30)
            # Pydantic-AI will return text and try to parse JSON; we will try to interpret
            try:
                decision = json.loads(run.text)
            except Exception:
                # fallback: assume continue
                decision = {"action": "continue", "reason": "couldn't parse agent reply"}

            if decision.get("action") == "replan":
                rprint("[yellow]Agent requested replanning after step - applying new steps.[/yellow]")
                new_steps_raw = decision.get("new_steps", [])
                # try to parse into Step objects
                new_steps: List[Step] = []
                for ns in new_steps_raw:
                    try:
                        new_steps.append(Step(**ns))
                    except Exception:
                        rprint(f"[red]Invalid new step from agent:[/red] {ns}")
                # Replace remaining steps with these
                # find current step index in plan.steps
                # naive: append at current position
                remaining = [s for s in plan.steps if s.idx > step.idx]
                plan.steps = plan.steps[:step.idx] + new_steps + remaining
                rprint(f"[green]Plan updated: {len(new_steps)} new steps inserted.[/green]")
                continue
            # else continue

        # If we don't have pydantic-ai or agent said continue, proceed to next

    return results


# ------------------------------- CLI entry --------------------------------

def main():
    parser = argparse.ArgumentParser(prog="ffai", description="FFmpeg AI CLI: plan and execute ffmpeg workflows via an LLM agent")
    parser.add_argument("prompt", nargs='+', help="Natural language instruction, e.g. 'convert input.mov to mp4 for youtube'")
    parser.add_argument("-y", action="store_true", help="Auto-approve the first plan (non-interactive)")
    parser.add_argument("--model", default="openrouter:moonshotai/kimi-k2-thinking", help="Model key for pydantic-ai (if installed)")
    args = parser.parse_args()

    text_prompt = ' '.join(args.prompt)

    ensure_ffmpeg()

    try:
        plan = build_plan_with_agent(text_prompt, model=args.model)
    except Exception as e:
        rprint(f"[red]Planning failed:[/red] {e}")
        sys.exit(1)

    present_plan(plan)

    if not args.y:
        ok = confirm("Approve plan?", default=False)
        if not ok:
            rprint("Aborted by user.")
            sys.exit(0)
    else:
        rprint("Auto-approved plan due to -y flag")

    results = execute_plan(plan)

    rprint(Panel("Execution complete. Summary:"))
    for r in results:
        rprint(f"Step {r.step_idx}: returncode={r.returncode} output={r.output_path} size={human_size(r.output_size)}")


if __name__ == '__main__':
    main()
