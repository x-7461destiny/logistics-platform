import { describe, expect, it } from "vitest";
import { actions, decodeClaims, type Booking } from "./domain";
const booking = (status: Booking["status"], driver_id: number | null = 5) =>
  ({ status, driver_id }) as Booking;

describe("role and state actions", () => {
  it("lets users cancel before pickup and complete delivered bookings", () => {
    expect(actions("user", booking("confirmed"))).toEqual(["cancelled"]);
    expect(actions("user", booking("goods_collected"))).toEqual([]);
    expect(actions("user", booking("delivered"))).toEqual(["completed"]);
  });
  it("lets drivers move delivery forward but not complete it", () => {
    expect(actions("driver", booking("confirmed"))).toEqual([
      "en_route",
      "cancelled",
    ]);
    expect(actions("driver", booking("en_route"))).toEqual([
      "goods_collected",
      "cancelled",
    ]);
    expect(actions("driver", booking("goods_collected"))).toEqual([
      "delivered",
    ]);
    expect(actions("driver", booking("delivered"))).toEqual([]);
  });
  it("allows admin cancellation after pickup and requires assignment to confirm", () => {
    expect(actions("admin", booking("goods_collected"))).toEqual([
      "delivered",
      "cancelled",
    ]);
    expect(actions("admin", booking("pending", null))).toEqual(["cancelled"]);
    expect(actions("admin", booking("pending"))).toEqual([
      "confirmed",
      "cancelled",
    ]);
  });
  it("has no actions for terminal states", () => {
    expect(actions("admin", booking("cancelled"))).toEqual([]);
    expect(actions("driver", booking("completed"))).toEqual([]);
  });
  it("tolerates invalid JWT display data", () => {
    expect(decodeClaims("invalid")).toEqual({});
  });
});
