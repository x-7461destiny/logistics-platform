import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { io, type Socket } from "socket.io-client";
import { ApiError, request, type LogEntry } from "./api";
import {
  actions,
  decodeClaims,
  labels,
  roleLabels,
  vehicles,
  type Booking,
  type Identity,
  type Role,
  type Status,
} from "./domain";

type Session = { token: string; identity: Identity; role: Role };
type Registration = {
  role: "user" | "driver";
  name: string;
  email: string;
  phone_number: string;
  password: string;
  vehicle_type?: string;
};
const actionLabels: Partial<Record<Status, string>> = {
  confirmed: "确认",
  cancelled: "取消订单",
  en_route: "出发",
  goods_collected: "取货",
  delivered: "送达",
  completed: "完成订单",
};
const date = (value: string) =>
  new Date(value).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai" });
const message = (error: unknown) =>
  error instanceof Error ? error.message : String(error);

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [restoring, setRestoring] = useState(true);
  const [authView, setAuthView] = useState<"login" | "register">("login");
  const [loginRole, setLoginRole] = useState<Role>("user");
  const [loginEmail, setLoginEmail] = useState("");
  const [authNotice, setAuthNotice] = useState("");
  const log = useCallback(
    (kind: string, text: string) =>
      setLogs((old) =>
        [
          { time: new Date().toLocaleTimeString(), kind, message: text },
          ...old,
        ].slice(0, 200),
      ),
    [],
  );
  const logout = useCallback(() => {
    sessionStorage.removeItem("logistics-token");
    setSession(null);
    setError("");
    setLogs([]);
  }, []);
  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  };
  const establish = useCallback(
    async (token: string, expected?: Role) => {
      const claims = decodeClaims(token);
      const isDriver = claims.principal_type === "driver";
      const identity = await request<Identity>(
        isDriver ? "/auth/driver-me" : "/auth/me",
        token,
        log,
      );
      const role = isDriver ? "driver" : (identity.role ?? "user");
      if (expected && role !== expected)
        throw new Error(
          `该账号实际身份为${roleLabels[role]}，请切换登录身份。`,
        );
      sessionStorage.setItem("logistics-token", token);
      setSession({ token, identity, role });
    },
    [log],
  );
  useEffect(() => {
    let alive = true;
    const token = sessionStorage.getItem("logistics-token");
    if (!token) {
      setRestoring(false);
      return;
    }
    const isDriver = decodeClaims(token).principal_type === "driver";
    void request<Identity>(
      isDriver ? "/auth/driver-me" : "/auth/me",
      token,
      log,
    )
      .then((identity) => {
        if (alive)
          setSession({
            token,
            identity,
            role: isDriver ? "driver" : (identity.role ?? "user"),
          });
      })
      .catch((e) => {
        if (alive) {
          logout();
          setError(`会话恢复失败：${message(e)}`);
        }
      })
      .finally(() => {
        if (alive) setRestoring(false);
      });
    return () => {
      alive = false;
    };
  }, [log, logout]);
  useEffect(() => {
    if (!session) return;
    const exp = Number(decodeClaims(session.token).exp);
    if (!exp) return;
    const timeout = window.setTimeout(
      () => {
        logout();
        setError("登录已过期，请重新登录。");
      },
      Math.max(0, exp * 1000 - Date.now()),
    );
    return () => window.clearTimeout(timeout);
  }, [session, logout]);
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-icon">↗</span> 物流联调台
        </div>
        <div className="eyebrow">LOGISTICS / SANDBOX</div>
        <nav>
          <a href="#orders">▤　订单中心</a>
          <a href="#driver">◎　司机工作台</a>
          <a href="#debug">⌘　调试面板</a>
        </nav>
        <div className="side-note">
          核心流程测试
          <br />
          <small>创建 → 配送 → 完成</small>
        </div>
      </aside>
      <main>
        <header>
          <div>
            <div className="eyebrow">DEVELOPMENT WORKSPACE</div>
            <h1>
              {session
                ? "运输工作台"
                : authView === "register"
                  ? "注册账号"
                  : "登录工作台"}
            </h1>
            <p>连接真实接口，验证每一步订单流转。</p>
          </div>
          {session && (
            <div className="account">
              <span>
                {session.identity.name} · {roleLabels[session.role]}
              </span>
              <button onClick={logout}>退出登录</button>
            </div>
          )}
        </header>
        {error && (
          <div className="banner error" role="alert">
            {error}
            <button onClick={() => setError("")}>关闭</button>
          </div>
        )}
        {!session && authNotice && (
          <div className="banner" role="status">
            {authNotice}
          </div>
        )}
        {restoring ? (
          <p>正在验证登录身份…</p>
        ) : !session ? (
          authView === "login" ? (
            <Login
              busy={busy}
              initialRole={loginRole}
              initialEmail={loginEmail}
              onRegister={(role) => {
                setLoginRole(role);
                setAuthNotice("");
                setError("");
                setAuthView("register");
              }}
              onLogin={(role, email, password) =>
                run(async () => {
                  const result = await request<{ access_token: string }>(
                    role === "driver" ? "/auth/driver-token" : "/auth/token",
                    "",
                    log,
                    {
                      method: "POST",
                      body: new URLSearchParams({ username: email, password }),
                    },
                  );
                  await establish(result.access_token, role);
                  setAuthNotice("");
                })
              }
            />
          ) : (
            <Register
              busy={busy}
              initialRole={loginRole === "driver" ? "driver" : "user"}
              onLogin={(role) => {
                setLoginRole(role);
                setError("");
                setAuthView("login");
              }}
              onRegister={(data) =>
                run(async () => {
                  const { role, ...body } = data;
                  await request<Identity>(
                    role === "driver"
                      ? "/auth/driver/register"
                      : "/auth/register",
                    "",
                    log,
                    { method: "POST", body: JSON.stringify(body) },
                  );
                  setLoginRole(role);
                  setLoginEmail(data.email);
                  setAuthNotice("注册成功，请使用新账号登录。");
                  setAuthView("login");
                })
              }
            />
          )
        ) : (
          <Workspace
            key={session.token}
            session={session}
            log={log}
            onUnauthorized={() => {
              logout();
              setError("登录失效，请重新登录。");
            }}
          />
        )}
        <section id="debug" className="panel debug">
          <div className="section-title">
            <div>
              <div className="eyebrow">INSPECTOR</div>
              <h2>调试面板</h2>
            </div>
            <button onClick={() => setLogs([])}>清空日志</button>
          </div>
          <div className="debug-grid">
            <div>
              <h3>当前 JWT 身份</h3>
              <p className="muted">解码信息仅供调试，权限由服务端校验。</p>
              <pre>
                {session
                  ? JSON.stringify(decodeClaims(session.token), null, 2)
                  : "尚未登录"}
              </pre>
            </div>
            <div>
              <h3>
                实时消息与 HTTP 错误 <small>最近 200 条</small>
              </h3>
              <div className="logs" aria-live="polite">
                {logs.length ? (
                  logs.map((entry, i) => (
                    <div className="log" key={i}>
                      <small>
                        {entry.time} · {entry.kind}
                      </small>
                      <pre>{entry.message}</pre>
                    </div>
                  ))
                ) : (
                  <p className="muted">暂无事件。登录后自动连接 WebSocket。</p>
                )}
              </div>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}

function Login({
  busy,
  initialRole,
  initialEmail,
  onRegister,
  onLogin,
}: {
  busy: boolean;
  initialRole: Role;
  initialEmail: string;
  onRegister: (role: Role) => void;
  onLogin: (role: Role, email: string, password: string) => Promise<void>;
}) {
  const [role, setRole] = useState<Role>(initialRole);
  return (
    <section className="panel login">
      <div className="eyebrow">WELCOME BACK</div>
      <h2>选择身份，开始联调</h2>
      <p className="muted">使用后端已有账号登录。</p>
      <div className="tabs">
        {(["user", "driver", "admin"] as Role[]).map((item) => (
          <button
            disabled={busy}
            aria-pressed={role === item}
            className={role === item ? "selected" : ""}
            onClick={() => setRole(item)}
            key={item}
          >
            {roleLabels[item]}
          </button>
        ))}
      </div>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          void onLogin(
            role,
            String(form.get("email")),
            String(form.get("password")),
          );
        }}
      >
        <label>
          邮箱
          <input
            name="email"
            type="email"
            autoComplete="username"
            placeholder="name@example.com"
            defaultValue={initialEmail}
            required
          />
        </label>
        <label>
          密码
          <input
            name="password"
            type="password"
            autoComplete="current-password"
            required
          />
        </label>
        <button className="primary" disabled={busy}>
          {busy ? "登录中…" : `以${roleLabels[role]}身份登录 →`}
        </button>
      </form>
      <p className="muted">管理员使用用户登录接口，实际角色由后端返回。</p>
      <p className="auth-switch">
        还没有账号？{" "}
        <button type="button" disabled={busy} onClick={() => onRegister(role)}>
          注册用户或司机账号
        </button>
      </p>
    </section>
  );
}

function Register({
  busy,
  initialRole,
  onLogin,
  onRegister,
}: {
  busy: boolean;
  initialRole: "user" | "driver";
  onLogin: (role: "user" | "driver") => void;
  onRegister: (data: Registration) => Promise<void>;
}) {
  const [role, setRole] = useState<"user" | "driver">(initialRole);
  const [validationError, setValidationError] = useState("");
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const name = String(form.get("name") ?? "").trim();
    const email = String(form.get("email") ?? "").trim();
    const phone_number = String(form.get("phone_number") ?? "").trim();
    const password = String(form.get("password") ?? "");
    const confirm = String(form.get("confirm_password") ?? "");
    if (!name || !email || !phone_number || !password) {
      setValidationError("请填写所有必填项。");
      return;
    }
    if (password !== confirm) {
      setValidationError("两次输入的密码不一致。");
      return;
    }
    setValidationError("");
    void onRegister({
      role,
      name,
      email,
      phone_number,
      password,
      ...(role === "driver"
        ? { vehicle_type: String(form.get("vehicle_type")) }
        : {}),
    });
  };
  return (
    <section className="panel login">
      <div className="eyebrow">CREATE ACCOUNT</div>
      <h2>注册新账号</h2>
      <p className="muted">选择身份后填写资料，注册完成即可登录。</p>
      <div className="tabs" role="group" aria-label="注册身份">
        {(["user", "driver"] as const).map((item) => (
          <button
            type="button"
            key={item}
            disabled={busy}
            aria-pressed={role === item}
            className={role === item ? "selected" : ""}
            onClick={() => {
              setRole(item);
              setValidationError("");
            }}
          >
            {roleLabels[item]}
          </button>
        ))}
      </div>
      <form onSubmit={submit}>
        <label>
          姓名
          <input name="name" autoComplete="name" required />
        </label>
        <label>
          邮箱
          <input name="email" type="email" autoComplete="email" required />
        </label>
        <label>
          手机号
          <input name="phone_number" type="tel" autoComplete="tel" required />
        </label>
        {role === "driver" && (
          <label>
            车型
            <select name="vehicle_type" required>
              {Object.entries(vehicles).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        )}
        <label>
          密码
          <input
            name="password"
            type="password"
            autoComplete="new-password"
            required
          />
        </label>
        <label>
          确认密码
          <input
            name="confirm_password"
            type="password"
            autoComplete="new-password"
            required
          />
        </label>
        {validationError && (
          <p className="form-error" role="alert">
            {validationError}
          </p>
        )}
        <button className="primary" disabled={busy}>
          {busy ? "注册中…" : `注册${roleLabels[role]}账号 →`}
        </button>
      </form>
      <p className="auth-switch">
        已有账号？{" "}
        <button type="button" disabled={busy} onClick={() => onLogin(role)}>
          返回登录
        </button>
      </p>
      <p className="muted">管理员账号由后端管理，不能在此自助注册。</p>
    </section>
  );
}

function Workspace({
  session,
  log,
  onUnauthorized,
}: {
  session: Session;
  log: (kind: string, text: string) => void;
  onUnauthorized: () => void;
}) {
  const { token, role } = session;
  const [bookings, setBookings] = useState<Booking[]>([]);
  const [current, setCurrent] = useState<Booking[]>([]);
  const [selected, setSelected] = useState<Booking | null>(null);
  const [offset, setOffset] = useState(0);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [identity, setIdentity] = useState(session.identity);
  const [connection, setConnection] = useState("连接中");
  const [position, setPosition] = useState<{
    latitude: number;
    longitude: number;
  } | null>(null);
  const socket = useRef<Socket | null>(null);
  const active = useRef(true);
  const selectedId = useRef<number | null>(null);
  const refreshSequence = useRef(0);
  const detailSequence = useRef(0);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  const api = useCallback(
    <T,>(path: string, init?: RequestInit) =>
      request<T>(path, token, log, init).catch((e) => {
        if (e instanceof ApiError && e.status === 401 && active.current)
          onUnauthorized();
        throw e;
      }),
    [token, log, onUnauthorized],
  );
  const apiRef = useRef(api);
  apiRef.current = api;
  const refresh = useCallback(async () => {
    const sequence = ++refreshSequence.current;
    setLoading(true);
    try {
      const list = await apiRef.current<Booking[]>(
        `/bookings?offset=${offset}&limit=20`,
      );
      if (active.current && sequence === refreshSequence.current)
        setBookings(list);
      if (role === "driver") {
        const [me, assigned] = await Promise.all([
          apiRef.current<Identity>("/auth/driver-me"),
          apiRef.current<Booking[]>("/bookings?active_only=true&limit=100"),
        ]);
        if (active.current && sequence === refreshSequence.current) {
          setIdentity(me);
          setCurrent(assigned);
        }
      }
    } finally {
      if (active.current && sequence === refreshSequence.current)
        setLoading(false);
    }
  }, [offset, role]);
  const openBooking = async (id: number) => {
    const sequence = ++detailSequence.current;
    selectedId.current = id;
    setSelected(null);
    const booking = await apiRef.current<Booking>(`/bookings/${id}`);
    if (active.current && sequence === detailSequence.current)
      setSelected(booking);
  };
  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await fn();
    } catch (e) {
      if (active.current) setError(message(e));
    } finally {
      if (active.current) setBusy(false);
    }
  };
  useEffect(() => {
    void refresh().catch((e) => {
      if (active.current) setError(message(e));
    });
  }, [refresh]);
  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;
  useEffect(() => {
    const client = io({ auth: { token }, transports: ["websocket"] });
    socket.current = client;
    client.on("connect", () => {
      setConnection("已连接");
      log("WebSocket", "连接成功");
      void refreshRef.current().catch((e) => setError(message(e)));
    });
    client.on("disconnect", (reason) => {
      setConnection("已断开");
      log("WebSocket", reason);
    });
    client.on("connect_error", (e) => {
      setConnection("连接失败");
      log("WebSocket 错误", e.message);
    });
    client.onAny((event: string, data: unknown) => {
      log(`WS / ${event}`, JSON.stringify(data, null, 2) ?? "");
      if (event === "error") setError(`WebSocket：${JSON.stringify(data)}`);
      if (
        event === "location_updated" &&
        data &&
        typeof data === "object" &&
        "latitude" in data &&
        "longitude" in data
      ) {
        setPosition({
          latitude: Number(data.latitude),
          longitude: Number(data.longitude),
        });
        setNotice("当前位置已上报。");
      }
      if (event.includes("booking") || event.includes("assignment"))
        void refreshRef.current().catch((e) => setError(message(e)));
    });
    return () => {
      client.removeAllListeners();
      client.offAny();
      client.disconnect();
      socket.current = null;
    };
  }, [token, log]);
  // Poll persisted state because not every backend transition emits a browser event.
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.hidden || busy) return;
      void refresh().catch((e) => {
        if (active.current) setError(message(e));
      });
      const id = selectedId.current;
      if (id) {
        const sequence = detailSequence.current;
        void apiRef
          .current<Booking>(`/bookings/${id}`)
          .then((data) => {
            if (
              active.current &&
              sequence === detailSequence.current &&
              selectedId.current === id
            )
              setSelected(data);
          })
          .catch((e) => {
            if (active.current) setError(message(e));
          });
      }
    }, 15000);
    return () => window.clearInterval(timer);
  }, [refresh, busy]);
  const updateStatus = (status: Status) =>
    run(async () => {
      if (!selected) return;
      const id = selected.booking_id;
      try {
        const result = await api<{ event_published: boolean }>(
          `/bookings/${id}/status`,
          {
            method: "PATCH",
            body: JSON.stringify({
              status,
              expected_version: selected.version,
            }),
          },
        );
        setNotice(
          result.event_published
            ? "订单状态已更新。"
            : "状态已保存，但事件发布失败；请以订单详情为准。",
        );
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) {
          await openBooking(id);
          throw new Error(`${e.message}。已重新加载，请核对后重试。`);
        }
        throw e;
      }
      await openBooking(id);
      await refresh();
    });
  return (
    <>
      {error && (
        <div className="banner error" role="alert">
          {error}
          <button onClick={() => setError("")}>关闭</button>
        </div>
      )}
      {notice && (
        <div className="banner" role="status">
          {notice}
        </div>
      )}
      <div className="metrics">
        <div>
          <span>当前身份</span>
          <strong>{roleLabels[role]}</strong>
        </div>
        <div>
          <span>当前页订单</span>
          <strong>{bookings.length.toString().padStart(2, "0")}</strong>
        </div>
        <div>
          <span>WebSocket</span>
          <strong className={connection === "已连接" ? "green" : ""}>
            {connection}
          </strong>
        </div>
        <div>
          <span>数据同步</span>
          <strong>15 秒</strong>
        </div>
      </div>
      {role === "driver" && (
        <section id="driver" className="panel">
          <div className="section-title">
            <div>
              <div className="eyebrow">DRIVER STATION</div>
              <h2>司机工作台</h2>
            </div>
            <span className="badge">
              {identity.is_available
                ? "在线 · 可接单"
                : current.length
                  ? "配送中 · 不可接单"
                  : "离线 · 不可接单"}
            </span>
          </div>
          <div className="driver-grid">
            <div>
              <p>
                {vehicles[identity.vehicle_type ?? ""]} · 司机 #{identity.id}
              </p>
              <div className="actions">
                <button
                  className="primary"
                  disabled={busy || identity.is_available || current.length > 0}
                  onClick={() =>
                    void run(async () => {
                      setIdentity(
                        await api<Identity>("/drivers/me/availability", {
                          method: "PATCH",
                          body: JSON.stringify({ is_available: true }),
                        }),
                      );
                      setNotice("已上线，请上报当前位置以便附近订单匹配。");
                    })
                  }
                >
                  上线接单
                </button>
                <button
                  disabled={busy || !identity.is_available}
                  onClick={() =>
                    void run(async () => {
                      setIdentity(
                        await api<Identity>("/drivers/me/availability", {
                          method: "PATCH",
                          body: JSON.stringify({ is_available: false }),
                        }),
                      );
                    })
                  }
                >
                  下线
                </button>
              </div>
              <p className="muted">
                上下线控制接单状态；WebSocket 连接状态单独显示。
              </p>
              <h3>当前订单</h3>
              {current.length ? (
                current.map((booking) => (
                  <button
                    className="order-link"
                    key={booking.booking_id}
                    onClick={() =>
                      void run(() => openBooking(booking.booking_id))
                    }
                  >
                    #{booking.booking_id} · {labels[booking.status]} →
                  </button>
                ))
              ) : (
                <p className="muted">暂无进行中的订单</p>
              )}
            </div>
            <div>
              <h3>当前位置</h3>
              <p className="muted">
                {position
                  ? `已上报：${position.latitude}, ${position.longitude}`
                  : "本次会话尚未上报位置"}
              </p>
              <LocationForm
                disabled={connection !== "已连接"}
                onError={setError}
                onSend={(latitude, longitude) => {
                  if (!socket.current?.connected) {
                    setError("WebSocket 未连接");
                    return;
                  }
                  socket.current.emit("update_location", {
                    driver_id: String(identity.id),
                    latitude,
                    longitude,
                  });
                  log(
                    "WS 发送",
                    JSON.stringify({
                      event: "update_location",
                      latitude,
                      longitude,
                    }),
                  );
                  setNotice("位置已发送，等待服务端确认。");
                }}
              />
            </div>
          </div>
        </section>
      )}
      {role !== "driver" && (
        <CreateBooking
          disabled={busy}
          onCreate={(body) =>
            run(async () => {
              const result = await api<{ booking_id: number; message: string }>(
                "/book",
                { method: "POST", body: JSON.stringify(body) },
              );
              setNotice(
                `订单 #${result.booking_id} 已创建，正在等待异步分配。`,
              );
              await openBooking(result.booking_id);
              await refresh();
            })
          }
        />
      )}
      <div id="orders" className="orders-grid">
        <section className="panel">
          <div className="section-title">
            <div>
              <div className="eyebrow">BOOKINGS</div>
              <h2>订单列表</h2>
            </div>
            <button
              disabled={loading || busy}
              onClick={() => void run(refresh)}
            >
              {loading ? "加载中…" : "刷新"}
            </button>
          </div>
          <p className="muted">
            {role === "admin"
              ? "全部订单"
              : role === "driver"
                ? "分配给我的订单"
                : "我的订单"}{" "}
            · 按最新创建排序
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>订单</th>
                  <th>状态</th>
                  <th>车型 / 价格</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {bookings.map((booking) => (
                  <tr
                    key={booking.booking_id}
                    className={
                      selected?.booking_id === booking.booking_id
                        ? "active-row"
                        : ""
                    }
                  >
                    <td>
                      <strong>#{booking.booking_id}</strong>
                      <small>{date(booking.date)}</small>
                    </td>
                    <td>
                      <span className={`badge status-${booking.status}`}>
                        {labels[booking.status]}
                      </span>
                    </td>
                    <td>
                      {vehicles[booking.vehicle_type] ?? booking.vehicle_type}
                      <small>{booking.price.toFixed(2)}</small>
                    </td>
                    <td>
                      <button
                        disabled={busy}
                        onClick={() =>
                          void run(() => openBooking(booking.booking_id))
                        }
                      >
                        详情 →
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!bookings.length && (
              <div className="empty">
                {loading ? "正在读取订单…" : "暂无订单"}
              </div>
            )}
          </div>
          <div className="pagination">
            <button
              disabled={offset === 0 || loading || busy}
              onClick={() => setOffset((old) => Math.max(0, old - 20))}
            >
              上一页
            </button>
            <span>第 {offset / 20 + 1} 页</span>
            <button
              disabled={bookings.length < 20 || loading || busy}
              onClick={() => setOffset((old) => old + 20)}
            >
              下一页
            </button>
          </div>
        </section>
        <section className="panel">
          <div className="section-title">
            <div>
              <div className="eyebrow">DETAIL & ACTIONS</div>
              <h2>订单详情</h2>
            </div>
          </div>
          <form
            className="inline-form"
            onSubmit={(e) => {
              e.preventDefault();
              const id = Number(new FormData(e.currentTarget).get("id"));
              void run(() => openBooking(id));
            }}
          >
            <input
              aria-label="订单编号"
              name="id"
              type="number"
              min="1"
              step="1"
              required
              placeholder="输入订单编号"
            />
            <button disabled={busy}>查询</button>
          </form>
          {selected ? (
            <>
              <div className="detail-head">
                <h2>#{selected.booking_id}</h2>
                <span className="badge">{labels[selected.status]}</span>
              </div>
              <dl>
                <dt>取货地点</dt>
                <dd>{selected.pickup_location}</dd>
                <dt>送货地点</dt>
                <dd>{selected.dropoff_location}</dd>
                <dt>司机</dt>
                <dd>{selected.driver_id ?? "等待分配"}</dd>
                <dt>车型 / 价格</dt>
                <dd>
                  {vehicles[selected.vehicle_type]} /{" "}
                  {selected.price.toFixed(2)}
                </dd>
                <dt>订单时间</dt>
                <dd>{date(selected.date)}（北京）</dd>
                <dt>版本</dt>
                <dd>{selected.version}</dd>
              </dl>
              <h3>状态操作</h3>
              <div className="actions">
                {actions(role, selected).map((status) => (
                  <button
                    className={status === "cancelled" ? "danger" : "primary"}
                    disabled={busy}
                    key={status}
                    onClick={() => void updateStatus(status)}
                  >
                    {actionLabels[status]}
                  </button>
                ))}
              </div>
              {!actions(role, selected).length && (
                <p className="muted">当前身份在此状态下无可用操作。</p>
              )}
              <h3>状态记录</h3>
              <ol className="timeline">
                {selected.status_history.map((entry, i) => (
                  <li key={i}>
                    <strong>{labels[entry.status]}</strong>
                    <small>{date(entry.timestamp)}</small>
                  </li>
                ))}
              </ol>
            </>
          ) : (
            <div className="empty">选择订单，查看详情和可用操作。</div>
          )}
        </section>
      </div>
    </>
  );
}

function CreateBooking({
  disabled,
  onCreate,
}: {
  disabled: boolean;
  onCreate: (body: Record<string, unknown>) => Promise<void>;
}) {
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const body: Record<string, unknown> = {
      vehicle_type: data.get("vehicle_type"),
    };
    for (const key of [
      "pickup_latitude",
      "pickup_longitude",
      "dropoff_latitude",
      "dropoff_longitude",
    ])
      body[key] = Number(data.get(key));
    body.scheduled_time = data.get("scheduled_time")
      ? `${data.get("scheduled_time")}:00+08:00`
      : null;
    void onCreate(body);
  };
  return (
    <section className="panel">
      <div className="section-title">
        <div>
          <div className="eyebrow">NEW SHIPMENT</div>
          <h2>创建订单</h2>
        </div>
        <span className="muted">留空预约时间即刻发货</span>
      </div>
      <form onSubmit={submit}>
        <div className="form-grid">
          {[
            ["pickup_latitude", "取货纬度", "31.2304", 90],
            ["pickup_longitude", "取货经度", "121.4737", 180],
            ["dropoff_latitude", "送货纬度", "31.2404", 90],
            ["dropoff_longitude", "送货经度", "121.4837", 180],
          ].map(([key, label, value, max]) => (
            <label key={key}>
              {label}
              <input
                name={String(key)}
                type="number"
                step="any"
                min={-Number(max)}
                max={Number(max)}
                defaultValue={value}
                required
              />
            </label>
          ))}
          <label>
            车型
            <select name="vehicle_type">
              {Object.entries(vehicles).map(([key, value]) => (
                <option value={key} key={key}>
                  {value}
                </option>
              ))}
            </select>
          </label>
          <label>
            预约时间（北京时间）
            <input name="scheduled_time" type="datetime-local" />
          </label>
        </div>
        <button className="primary" disabled={disabled}>
          {disabled ? "处理中…" : "创建订单 →"}
        </button>
      </form>
    </section>
  );
}

function LocationForm({
  disabled,
  onSend,
  onError,
}: {
  disabled: boolean;
  onSend: (latitude: number, longitude: number) => void;
  onError: (text: string) => void;
}) {
  const [latitude, setLatitude] = useState("31.2304");
  const [longitude, setLongitude] = useState("121.4737");
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSend(Number(latitude), Number(longitude));
      }}
    >
      <div className="form-grid">
        <label>
          纬度
          <input
            type="number"
            required
            step="any"
            min="-90"
            max="90"
            value={latitude}
            onChange={(e) => setLatitude(e.target.value)}
          />
        </label>
        <label>
          经度
          <input
            type="number"
            required
            step="any"
            min="-180"
            max="180"
            value={longitude}
            onChange={(e) => setLongitude(e.target.value)}
          />
        </label>
      </div>
      <div className="actions">
        <button disabled={disabled} className="primary">
          上报位置
        </button>
        <button
          type="button"
          onClick={() => {
            if (!navigator.geolocation) {
              onError("浏览器不支持定位，请手动填写坐标。");
              return;
            }
            navigator.geolocation.getCurrentPosition(
              (p) => {
                setLatitude(String(p.coords.latitude));
                setLongitude(String(p.coords.longitude));
              },
              (e) => onError(`定位失败：${e.message}`),
              { timeout: 10000 },
            );
          }}
        >
          获取浏览器位置
        </button>
      </div>
    </form>
  );
}
