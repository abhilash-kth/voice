export type CallState =
    | "idle"
    | "connecting"
    | "waiting_for_agent"
    | "connected"
    | "ending"
    | "ended"
    | "error";