"use client";

import { createClient } from "@supabase/supabase-js";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

if (!url || !anonKey) {
  // Surfaced at runtime in the browser console — the demo view degrades to an
  // explicit error state rather than crashing.
  // eslint-disable-next-line no-console
  console.warn("Supabase env vars missing — set NEXT_PUBLIC_SUPABASE_URL / _ANON_KEY in .env.local");
}

export const supabase = createClient(url ?? "", anonKey ?? "", {
  auth: { persistSession: false },
});

export const CLAIM_DOCS_BUCKET = "claim-docs";
