import AsyncStorage from '@react-native-async-storage/async-storage';
import { Platform } from 'react-native';

/**
 * 本地端登入：帳號存在自己後端的 SQLite，不依賴任何雲端登入服務。
 *
 * 登入成功後後端發一組 access token，存在瀏覽器 localStorage（手機是
 * AsyncStorage），之後每個 API 請求都帶 `Authorization: Bearer <token>`。
 */

export type AuthSession = {
  accessToken: string;
  expiresAt: string;
  user: { id: string; email: string };
};

type SessionResponse = {
  access_token: string;
  expires_at: string;
  user: { id: string; email: string };
};

const SESSION_KEY = 'nutrilens.auth.session';

// 預設要登入，跟後端一致；只有明確設 false 才跳過登入、直接用 demo_user。
export const isAuthRequired = process.env.EXPO_PUBLIC_AUTH_REQUIRED?.trim().toLowerCase() !== 'false';

const sessionStorage = Platform.OS === 'web'
  ? {
      getItem: async (key: string) => (typeof window === 'undefined' ? null : window.localStorage.getItem(key)),
      setItem: async (key: string, value: string) => {
        if (typeof window !== 'undefined') window.localStorage.setItem(key, value);
      },
      removeItem: async (key: string) => {
        if (typeof window !== 'undefined') window.localStorage.removeItem(key);
      },
    }
  : AsyncStorage;

function toSession(data: SessionResponse): AuthSession {
  return { accessToken: data.access_token, expiresAt: data.expires_at, user: data.user };
}

async function saveSession(session: AuthSession | null) {
  if (session) await sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
  else await sessionStorage.removeItem(SESSION_KEY);
}

async function postAuth(apiBaseUrl: string, path: string, body: object): Promise<AuthSession> {
  const resp = await fetch(`${apiBaseUrl}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await resp.json().catch(() => null);
  if (!resp.ok) throw new Error(data?.error || `登入服務錯誤（HTTP ${resp.status}）`);
  const session = toSession(data as SessionResponse);
  await saveSession(session);
  return session;
}

// 帳號用暱稱，沿用 API 原本的 email 欄位傳送；舊帳號的 Email 就是它的暱稱
export function signIn(apiBaseUrl: string, nickname: string, password: string) {
  return postAuth(apiBaseUrl, '/auth/login', { email: nickname, password });
}

export function signUp(apiBaseUrl: string, nickname: string, password: string, inviteCode?: string) {
  const body = { email: nickname, password };
  return postAuth(apiBaseUrl, '/auth/signup', inviteCode ? { ...body, invite_code: inviteCode } : body);
}

/** open：直接註冊；code：要邀請碼（從其他裝置或 tunnel 連進來時）；closed：不開放註冊。 */
export type SignupMode = 'open' | 'code' | 'closed';

export async function fetchSignupMode(apiBaseUrl: string): Promise<SignupMode> {
  try {
    const resp = await fetch(`${apiBaseUrl}/auth/config`);
    const data = await resp.json();
    if (data?.signup === 'code' || data?.signup === 'closed') return data.signup;
  } catch {
    // 問不到就照常顯示註冊表單，真正擋不擋由後端決定
  }
  return 'open';
}

export async function signOut(apiBaseUrl: string, accessToken: string | null) {
  // 先清本機的 session：就算後端連不上，這台裝置也一定會登出。
  await saveSession(null);
  if (!accessToken) return;
  try {
    await fetch(`${apiBaseUrl}/auth/logout`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${accessToken}` },
    });
  } catch {
    // 後端那邊的 token 30 天後自己會過期
  }
}

/**
 * 讀回上次的登入狀態。後端明確說 token 失效（401）才清掉；
 * 連不上後端時先保留，等後端起來再由各個 API 的回應決定。
 */
export async function restoreSession(apiBaseUrl: string): Promise<AuthSession | null> {
  let session: AuthSession | null = null;
  try {
    const raw = await sessionStorage.getItem(SESSION_KEY);
    session = raw ? JSON.parse(raw) as AuthSession : null;
  } catch {
    session = null;
  }
  if (!session?.accessToken) return null;
  if (Date.parse(session.expiresAt) <= Date.now()) {
    await saveSession(null);
    return null;
  }

  try {
    const resp = await fetch(`${apiBaseUrl}/auth/user`, {
      headers: { Authorization: `Bearer ${session.accessToken}` },
    });
    if (resp.status === 401) {
      await saveSession(null);
      return null;
    }
  } catch {
    // 後端還沒開，先沿用
  }
  return session;
}

/** 這台裝置上的登入狀態清掉（後端那邊不用通知，token 已經沒用了）。 */
export function clearStoredSession() {
  return saveSession(null);
}

/**
 * 同一個網站開了好幾個分頁時，在其中一個登入、登出或換帳號，其他分頁跟著變。
 * 先前各分頁各自記著自己的狀態，另一頁登出了，這一頁還以為自己登入著，
 * 每個操作都回「沒有權限」。只有網頁版有這個問題。
 */
export function subscribeToSessionChanges(listener: (session: AuthSession | null) => void): () => void {
  if (Platform.OS !== 'web' || typeof window === 'undefined') return () => {};
  const handler = (event: StorageEvent) => {
    // key 是 null 代表整個 localStorage 被清掉
    if (event.key !== SESSION_KEY && event.key !== null) return;
    let session: AuthSession | null = null;
    try {
      session = event.newValue ? JSON.parse(event.newValue) as AuthSession : null;
    } catch {
      session = null;
    }
    listener(session);
  };
  window.addEventListener('storage', handler);
  return () => window.removeEventListener('storage', handler);
}

// 用網頁事件而不是模組變數：lib/scanner.ts 會被 Node 的測試直接載入，
// 不能 import 這個檔案，只能自己送同名事件。
export const UNAUTHORIZED_EVENT = 'nutrilens:unauthorized';

/** 後端回 401：token 過期、在其他分頁登出、或後端換了資料庫。由 AuthGate 帶回登入畫面。 */
export function onUnauthorized(listener: () => void): () => void {
  if (typeof window === 'undefined' || typeof window.addEventListener !== 'function') return () => {};
  window.addEventListener(UNAUTHORIZED_EVENT, listener);
  return () => window.removeEventListener(UNAUTHORIZED_EVENT, listener);
}

export function reportUnauthorized() {
  if (typeof window !== 'undefined' && typeof window.dispatchEvent === 'function') {
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
  }
}
