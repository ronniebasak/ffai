const std = @import("std");

/// Represents a chat message with role and content
pub const Message = struct {
    role: []const u8,
    content: []const u8,
};

/// Request configuration for the Groq API
pub const ChatRequest = struct {
    messages: []const Message,
    model: []const u8,
    temperature: f32,
    max_completion_tokens: u32,
    top_p: f32,
    stream: bool,
    stop: ?[]const u8,

    pub fn toJson(self: ChatRequest, allocator: std.mem.Allocator) ![]u8 {
        std.debug.print("[DEBUG] ChatRequest.toJson: Starting JSON generation\n", .{});
        
        var list: std.ArrayList(u8) = .empty;
        errdefer list.deinit(allocator);

        const writer = list.writer(allocator);

        try writer.writeAll("{\"messages\":[");
        for (self.messages, 0..) |msg, i| {
            if (i > 0) try writer.writeAll(",");
            try writer.print("{{\"role\":\"{s}\",\"content\":\"{s}\"}}", .{ msg.role, msg.content });
        }
        try writer.writeAll("],");

        try writer.print("\"model\":\"{s}\",", .{self.model});
        try writer.print("\"temperature\":{d},", .{self.temperature});
        try writer.print("\"max_completion_tokens\":{d},", .{self.max_completion_tokens});
        try writer.print("\"top_p\":{d},", .{self.top_p});
        try writer.print("\"stream\":{s},", .{if (self.stream) "true" else "false"});
        try writer.print("\"stop\":{s}", .{if (self.stop) |_| "null" else "null"});
        try writer.writeAll("}");

        const json_body = try list.toOwnedSlice(allocator);
        std.debug.print("[DEBUG] ChatRequest.toJson: Generated JSON body:\n{s}\n", .{json_body});
        
        return json_body;
    }
};

/// Represents a streaming response chunk from the API
pub const StreamChunk = struct {
    id: []const u8,
    object: []const u8,
    created: u64,
    model: []const u8,
    choices: []Choice,

    pub const Choice = struct {
        index: u32,
        delta: Delta,
        finish_reason: ?[]const u8,
    };

    pub const Delta = struct {
        role: ?[]const u8,
        content: ?[]const u8,
    };
};
