// Firebase initialization and auth helper utilities
// Replace the below config with your Firebase project settings (env-driven preferred)
import { initializeApp } from 'firebase/app';
import { getFirestore, doc, getDoc, setDoc, serverTimestamp } from 'firebase/firestore';
import { getAuth, onAuthStateChanged, signInWithEmailAndPassword, createUserWithEmailAndPassword, signOut, User, GoogleAuthProvider, signInWithPopup } from 'firebase/auth';

const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
};

let _app: ReturnType<typeof initializeApp> | null = null;
export function getFirebaseApp() {
  if (!_app) _app = initializeApp(firebaseConfig);
  return _app;
}

export function getFirebaseAuth() {
  return getAuth(getFirebaseApp());
}

export function authStateListener(cb: (user: User | null)=>void) {
  return onAuthStateChanged(getFirebaseAuth(), cb);
}

export async function emailPasswordSignUp(email: string, password: string) {
  const auth = getFirebaseAuth();
  const cred = await createUserWithEmailAndPassword(auth, email, password);
  return cred.user;
}

export async function emailPasswordSignIn(email: string, password: string) {
  const auth = getFirebaseAuth();
  const cred = await signInWithEmailAndPassword(auth, email, password);
  return cred.user;
}

export async function logout() { await signOut(getFirebaseAuth()); }

// Google SSO
const _googleProvider = new GoogleAuthProvider();
export async function googleSignIn() {
  const auth = getFirebaseAuth();
  const cred = await signInWithPopup(auth, _googleProvider);
  return cred.user;
}

// Firestore helpers
let _db: ReturnType<typeof getFirestore> | null = null;
export function getDb() {
  if (!_db) _db = getFirestore(getFirebaseApp());
  return _db;
}

export interface UserDataDoc {
  entries: any[]; // ResumeEntry-like objects
  jobDescription?: string;
  format?: string; // 'latex' | 'word'
  updatedAt?: any;
}

export async function loadUserData(uid: string): Promise<UserDataDoc | null> {
  const ref = doc(getDb(), 'users', uid);
  const snap = await getDoc(ref);
  if (!snap.exists()) return null;
  return snap.data() as UserDataDoc;
}

export async function saveUserData(uid: string, data: Partial<UserDataDoc>) {
  const ref = doc(getDb(), 'users', uid);
  await setDoc(ref, { ...data, updatedAt: serverTimestamp() }, { merge: true });
}

// Extract only "experience" style entries (exclude purely personal info & optionally education/certification)
function extractExperience(entries: any[] | undefined) {
  if (!Array.isArray(entries)) return [] as any[];
  return entries.filter(e => e && typeof e === 'object' && !['info'].includes(e.type));
}

function normalizeExperience(entries: any[]) {
  // Create a stable representation ignoring ordering differences by sorting
  const key = (e: any) => [e.type||'', e.role||'', e.company||'', e.start||'', e.end||'', e.location||''].join('|').toLowerCase();
  return [...entries]
    .map(e => ({
      type: e.type,
      role: e.role,
      company: e.company,
      location: e.location,
      start: e.start,
      end: e.end,
      description: e.description,
      role_description: e.role_description
    }))
    .sort((a,b)=> key(a).localeCompare(key(b)));
}

export async function saveUserDataIfExperienceChanged(uid: string, data: Partial<UserDataDoc>): Promise<{updated:boolean; reason:string}> {
  try {
    const ref = doc(getDb(), 'users', uid);
    const snap = await getDoc(ref);
    if (!snap.exists()) {
      await setDoc(ref, { ...data, updatedAt: serverTimestamp() });
      return { updated: true, reason: 'no-existing-doc' };
    }
    const prev = snap.data() as UserDataDoc;
    const prevNorm = normalizeExperience(extractExperience(prev.entries));
    const nextNorm = normalizeExperience(extractExperience(data.entries));
    const same = JSON.stringify(prevNorm) === JSON.stringify(nextNorm);
    if (same) {
      return { updated: false, reason: 'experience-unchanged' };
    }
    await setDoc(ref, { ...data, updatedAt: serverTimestamp() }, { merge: true });
    return { updated: true, reason: 'experience-changed' };
  } catch (e:any) {
    // Fallback: attempt normal save to avoid data loss if comparison failed
    try { await saveUserData(uid, data); return { updated: true, reason: 'fallback-error-compare' }; } catch {}
    return { updated: false, reason: 'error:'+ (e?.message||'unknown') };
  }
}
