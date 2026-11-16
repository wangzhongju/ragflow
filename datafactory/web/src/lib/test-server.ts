import { setupServer } from "msw/node";

// Start interception before openapi-fetch captures the fetch implementation.
export const Server = setupServer();
Server.listen({ onUnhandledRequest: "error" });
