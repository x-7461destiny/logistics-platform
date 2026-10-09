export type Role = "user" | "driver" | "admin";
export type Status =
  | "pending"
  | "scheduled"
  | "confirmed"
  | "en_route"
  | "goods_collected"
  | "delivered"
  | "completed"
  | "cancelled";
export interface Identity {
  id: number;
  name: string;
  email: string;
  role?: Role;
  is_available?: boolean;
  vehicle_type?: string;
}
export interface Booking {
  booking_id: number;
  driver_id: number | null;
  version: number;
  status: Status;
  pickup_location: string;
  dropoff_location: string;
  vehicle_type: string;
  price: number;
  date: string;
  status_history: { status: Status; timestamp: string }[];
}
export const labels: Record<Status, string> = {
  pending: "待分配",
  scheduled: "已预约",
  confirmed: "已确认",
  en_route: "前往取货",
  goods_collected: "已取货",
  delivered: "已送达",
  completed: "已完成",
  cancelled: "已取消",
};
export const roleLabels: Record<Role, string> = {
  user: "用户",
  driver: "司机",
  admin: "管理员",
};
export const vehicles: Record<string, string> = {
  van: "厢式货车",
  truck: "货车",
  refrigerated_truck: "冷藏车",
};
const transitions: Record<Status, Status[]> = {
  pending: ["confirmed", "cancelled"],
  scheduled: ["confirmed", "cancelled"],
  confirmed: ["en_route", "cancelled"],
  en_route: ["goods_collected", "cancelled"],
  goods_collected: ["delivered", "cancelled"],
  delivered: ["completed"],
  completed: [],
  cancelled: [],
};
export function actions(role: Role, booking: Booking): Status[] {
  return transitions[booking.status].filter((target) => {
    if (target === "confirmed" && booking.driver_id === null) return false;
    if (role === "admin") return true;
    if (target === "cancelled") return booking.status !== "goods_collected";
    return role === "user" ? target === "completed" : target !== "completed";
  });
}
export function decodeClaims(token: string): Record<string, unknown> {
  try {
    const part = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(
      new TextDecoder().decode(
        Uint8Array.from(atob(part), (c) => c.charCodeAt(0)),
      ),
    );
  } catch {
    return {};
  }
}
