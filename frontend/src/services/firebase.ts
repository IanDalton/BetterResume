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
