const std = @import("std");

pub fn run() !void {
    var arena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
    defer arena.deinit();
    const allocator = arena.allocator();

    var client = std.http.Client{ .allocator = allocator };
    defer client.deinit();

    const uri = try std.Uri.parse("https://postman-echo.com/get");

    std.debug.print("Sending REQ", .{});
    var req = try client.request(
        .GET,
        uri,
        .{},
    );
    std.debug.print("REQ Sent!", .{});
    defer req.deinit();

    // No body to send for GET
    try req.sendBodiless();

    const body = try req.reader.receiveHead();
    defer allocator.free(body);

    std.debug.print("{s}", .{body});
}
