const std = @import("std");
const types = @import("types.zig");

pub const GroqClient = struct {
    allocator: std.mem.Allocator,
    api_key: []const u8,
    base_url: []const u8 = "https://api.groq.com",

    pub fn init(allocator: std.mem.Allocator) !GroqClient {
        std.debug.print("[DEBUG] GroqClient.init: Loading API key from environment\n", .{});
        const api_key = try std.process.getEnvVarOwned(allocator, "GROQ_API_KEY");
        errdefer allocator.free(api_key);
        
        // Log first 10 chars of API key for verification (security)
        const preview_len = @min(10, api_key.len);
        std.debug.print("[DEBUG] GroqClient.init: API key loaded (first {d} chars: {s}...)\n", .{preview_len, api_key[0..preview_len]});

        return .{
            .allocator = allocator,
            .api_key = api_key,
        };
    }

    pub fn deinit(self: *GroqClient) void {
        self.allocator.free(self.api_key);
    }

    pub fn chatCompletion(
        self: *GroqClient,
        request: types.ChatRequest,
        callback: *const fn (content: []const u8) void,
    ) !void {
        std.debug.print("[DEBUG] chatCompletion: Starting HTTP client\n", .{});
        var client = std.http.Client{ .allocator = self.allocator };
        defer client.deinit();

        // Build URL
        const url = try std.fmt.allocPrint(self.allocator, "{s}/openai/v1/chat/completions", .{self.base_url});
        defer self.allocator.free(url);
        std.debug.print("[DEBUG] chatCompletion: Target URL: {s}\n", .{url});

        const uri = try std.Uri.parse(url);

        // JSON body
        const json_body = try request.toJson(self.allocator);
        defer self.allocator.free(json_body);
        std.debug.print("[DEBUG] chatCompletion: Request body length: {d} bytes\n", .{json_body.len});

        // Authorization header
        const auth_header = try std.fmt.allocPrint(self.allocator, "Bearer {s}", .{self.api_key});
        defer self.allocator.free(auth_header);

        const extra_headers = [_]std.http.Header{
            .{ .name = "Content-Type", .value = "application/json" },
            .{ .name = "Authorization", .value = auth_header },
        };

        // Make the request
        std.debug.print("[DEBUG] chatCompletion: Creating HTTP request\n", .{});
        var req = try client.request(.POST, uri, .{ .extra_headers = &extra_headers });
        defer req.deinit();

        // Provide content length and send body
        std.debug.print("[DEBUG] chatCompletion: Sending request body\n", .{});
        req.transfer_encoding = .{ .content_length = json_body.len };
        try req.sendBodyComplete(json_body);

        // Receive headers
        std.debug.print("[DEBUG] chatCompletion: Waiting for response headers\n", .{});
        var redirect_buf: [0]u8 = undefined;
        var response = try req.receiveHead(&redirect_buf);
        
        std.debug.print("[DEBUG] chatCompletion: Response received, starting to read response body\n", .{});

        // Streamed body reader with an internal buffer for line-delimited reads
        var transfer_buf: [4096]u8 = undefined;
        var reader = response.reader(&transfer_buf);

        // Read SSE lines: "data: {...}" or "data: [DONE]"
        var line_count: usize = 0;
        while (true) {
            const line = reader.takeDelimiterExclusive('\n') catch |err| switch (err) {
                error.EndOfStream => {
                    std.debug.print("[DEBUG] chatCompletion: End of stream reached after {d} lines\n", .{line_count});
                    break;
                },
                // If your provider ever sends a very long line, decide how to handle it.
                // For now bubble it up.
                else => {
                    std.debug.print("[DEBUG] chatCompletion: Error reading line: {any}\n", .{err});
                    return err;
                },
            };

            line_count += 1;

            // Trim trailing '\r' for CRLF bodies
            const trimmed = blk: {
                if (line.len > 0 and line[line.len - 1] == '\r') break :blk line[0 .. line.len - 1];
                break :blk line;
            };

            std.debug.print("[DEBUG] chatCompletion: Line {d} (length {d}): {s}\n", .{line_count, trimmed.len, trimmed});

            if (trimmed.len == 0) continue;

            if (std.mem.startsWith(u8, trimmed, "data: ")) {
                const json_str = trimmed[6..];
                std.debug.print("[DEBUG] chatCompletion: Found data line, JSON: {s}\n", .{json_str});

                if (std.mem.eql(u8, json_str, "[DONE]")) {
                    std.debug.print("[DEBUG] chatCompletion: Received [DONE] signal\n", .{});
                    break;
                }

                if (try self.parseStreamChunk(json_str)) |content| {
                    std.debug.print("[DEBUG] chatCompletion: Parsed content: '{s}'\n", .{content});
                    std.debug.print("[DEBUG] chatCompletion: Invoking callback\n", .{});
                    callback(content);
                } else {
                    std.debug.print("[DEBUG] chatCompletion: parseStreamChunk returned null\n", .{});
                }
            }
        }
        std.debug.print("[DEBUG] chatCompletion: Completed processing response\n", .{});
    }

    fn parseStreamChunk(self: *GroqClient, json_str: []const u8) !?[]const u8 {
        std.debug.print("[DEBUG] parseStreamChunk: Attempting to parse JSON\n", .{});
        const parsed = std.json.parseFromSlice(std.json.Value, self.allocator, json_str, .{}) catch |err| {
            std.debug.print("[DEBUG] parseStreamChunk: JSON parse error: {any}\n", .{err});
            return null;
        };
        defer parsed.deinit();

        const root = parsed.value;
        std.debug.print("[DEBUG] parseStreamChunk: JSON parsed successfully\n", .{});

        // Navigate: root.choices[0].delta.content
        if (root.object.get("choices")) |choices_value| {
            std.debug.print("[DEBUG] parseStreamChunk: Found 'choices' field\n", .{});
            if (choices_value.array.items.len > 0) {
                std.debug.print("[DEBUG] parseStreamChunk: choices array has {d} items\n", .{choices_value.array.items.len});
                const first_choice = choices_value.array.items[0];
                if (first_choice.object.get("delta")) |delta| {
                    std.debug.print("[DEBUG] parseStreamChunk: Found 'delta' field\n", .{});
                    if (delta.object.get("content")) |content| {
                        std.debug.print("[DEBUG] parseStreamChunk: Found 'content' field\n", .{});
                        if (content == .string) {
                            std.debug.print("[DEBUG] parseStreamChunk: Content is string: '{s}'\n", .{content.string});
                            return content.string;
                        } else {
                            std.debug.print("[DEBUG] parseStreamChunk: Content is not a string\n", .{});
                        }
                    } else {
                        std.debug.print("[DEBUG] parseStreamChunk: No 'content' field in delta\n", .{});
                    }
                } else {
                    std.debug.print("[DEBUG] parseStreamChunk: No 'delta' field in choice\n", .{});
                }
            } else {
                std.debug.print("[DEBUG] parseStreamChunk: choices array is empty\n", .{});
            }
        } else {
            std.debug.print("[DEBUG] parseStreamChunk: No 'choices' field in root\n", .{});
        }
        return null;
    }
};

/// Simple helper function to make a chat completion call
pub fn chat(
    allocator: std.mem.Allocator,
    user_message: []const u8,
    callback: *const fn (content: []const u8) void,
) !void {
    var client = try GroqClient.init(allocator);
    defer client.deinit();

    const messages = [_]types.Message{
        .{ .role = "user", .content = user_message },
    };

    const request = types.ChatRequest{
        .messages = &messages,
        .model = "moonshotai/kimi-k2-instruct-0905",
        .temperature = 0.6,
        .max_completion_tokens = 4096,
        .top_p = 1.0,
        .stream = true,
        .stop = null,
    };

    try client.chatCompletion(request, callback);
}
