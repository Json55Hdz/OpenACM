/**
 * Browsers record voice as webm/opus, which audio models reject. Convert it to 16 kHz mono
 * 16-bit WAV in the browser (small: ~1.9 MB per minute) so any audio-capable model accepts it
 * and no server-side ffmpeg is needed.
 */
export async function blobToWav(blob: Blob, targetRate = 16000): Promise<Blob> {
  const ctx = new AudioContext();
  try {
    const decoded = await ctx.decodeAudioData(await blob.arrayBuffer());
    const frames = Math.max(1, Math.ceil(decoded.duration * targetRate));
    const offline = new OfflineAudioContext(1, frames, targetRate);
    const src = offline.createBufferSource();
    src.buffer = decoded;
    src.connect(offline.destination);
    src.start();
    const pcm = (await offline.startRendering()).getChannelData(0);

    const out = new DataView(new ArrayBuffer(44 + pcm.length * 2));
    const text = (o: number, s: string) => { for (let i = 0; i < s.length; i++) out.setUint8(o + i, s.charCodeAt(i)); };
    text(0, 'RIFF'); out.setUint32(4, 36 + pcm.length * 2, true); text(8, 'WAVE'); text(12, 'fmt ');
    out.setUint32(16, 16, true); out.setUint16(20, 1, true); out.setUint16(22, 1, true);
    out.setUint32(24, targetRate, true); out.setUint32(28, targetRate * 2, true);
    out.setUint16(32, 2, true); out.setUint16(34, 16, true); text(36, 'data'); out.setUint32(40, pcm.length * 2, true);
    for (let i = 0; i < pcm.length; i++) {
      const v = Math.max(-1, Math.min(1, pcm[i]));
      out.setInt16(44 + i * 2, v < 0 ? v * 0x8000 : v * 0x7fff, true);
    }
    return new Blob([out], { type: 'audio/wav' });
  } finally {
    void ctx.close();
  }
}
