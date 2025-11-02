const std = @import("std");
// const groq = @import("groq/handler.zig");
const httptest = @import("httptest/httptest.zig");

fn printContent(content: []const u8) void {
    std.debug.print("[DEBUG] printContent: Callback invoked with content: '{s}'\n", .{content});
    std.debug.print("{s}", .{content});
}

pub fn main() !void {
    std.debug.print("[DEBUG] main: Program started\n", .{});

    // var gpa = std.heap.GeneralPurposeAllocator(.{}){};
    // defer _ = gpa.deinit();
    // const allocator = gpa.allocator();

    std.debug.print("[DEBUG] main: Allocator created\n", .{});
    std.debug.print("Making Groq API call...\n\n", .{});

    // Make a simple chat completion request
    std.debug.print("[DEBUG] main: Calling groq.chat\n", .{});
    try httptest.run();
    // groq.chat(
    //     allocator,
    //     "Hello! Tell me a short joke.",
    //     &printContent,
    // ) catch |err| {
    //     std.debug.print("[ERROR] main: groq.chat failed with error: {any}\n", .{err});
    //     return err;
    // };

    std.debug.print("\n\n[DEBUG] main: API call completed!\n", .{});
}

test "simple test" {
    const gpa = std.testing.allocator;
    var list: std.ArrayList(i32) = .empty;
    defer list.deinit(gpa); // Try commenting this out and see if zig detects the memory leak!
    try list.append(gpa, 42);
    try std.testing.expectEqual(@as(i32, 42), list.pop());
}

test "fuzz example" {
    const Context = struct {
        fn testOne(context: @This(), input: []const u8) anyerror!void {
            _ = context;
            // Try passing `--fuzz` to `zig build test` and see if it manages to fail this test case!
            try std.testing.expect(!std.mem.eql(u8, "canyoufindme", input));
        }
    };
    try std.testing.fuzz(Context{}, Context.testOne, .{});
}
