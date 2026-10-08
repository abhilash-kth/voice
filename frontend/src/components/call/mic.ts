// Browser mic pre-flight (moved from CallPanel): assure permission + warm the
// AudioContext before startCall, so a denied mic fails BEFORE a room opens.

/** Throws with a user-facing message when the mic can't be opened. */
export async function ensureMicReady(): Promise<void> {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
    stream.getTracks().forEach((t) => t.stop());
    const AC =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext?: typeof AudioContext })
        .webkitAudioContext;
    if (AC) await new AC().resume();
  } catch {
    throw new Error(
      "Microphone access denied. Please allow microphone access in your browser settings.",
    );
  }
}
