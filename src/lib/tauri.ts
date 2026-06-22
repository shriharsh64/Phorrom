// Thin wrapper over Tauri commands, safe to import in a plain browser (degrades to no-ops).
import { invoke } from "@tauri-apps/api/core";

export const isTauri = (): boolean =>
  typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

/** Which managed provider keys are stored in the OS keychain. Empty in browser mode. */
export async function secretStatus(): Promise<Record<string, boolean>> {
  if (!isTauri()) return {};
  return invoke<Record<string, boolean>>("secret_status");
}

/** Persist a provider key to the OS keychain (empty value clears it). No-op in browser. */
export async function setSecret(key: string, value: string): Promise<void> {
  if (!isTauri()) return;
  await invoke("set_secret", { key, value });
}
