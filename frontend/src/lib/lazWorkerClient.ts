import type {
  LazDecodeRequest,
  LazDecodeResult,
  LazDecodeSuccess,
} from "./laz";

interface PendingDecode {
  resolve: (result: LazDecodeSuccess) => void;
  reject: (reason: Error) => void;
}

export class LazWorkerClient {
  private readonly worker = new Worker(
    new URL("../workers/lazrs-worker.ts", import.meta.url),
    { type: "module" },
  );
  private readonly pending = new Map<number, PendingDecode>();
  private nextId = 1;

  constructor() {
    this.worker.onmessage = (event: MessageEvent<LazDecodeResult>) => {
      const request = this.pending.get(event.data.id);
      if (!request) return;
      this.pending.delete(event.data.id);
      if (event.data.type === "error") {
        request.reject(new Error(event.data.message));
      } else {
        request.resolve(event.data);
      }
    };
    this.worker.onerror = (event) => {
      const reason = new Error(
        event.message || "The LAS 1.4 decoder stopped unexpectedly.",
      );
      for (const request of this.pending.values()) request.reject(reason);
      this.pending.clear();
    };
  }

  decode(
    buffer: ArrayBuffer,
    options: Omit<LazDecodeRequest, "buffer" | "id"> = {},
  ) {
    const id = this.nextId;
    this.nextId += 1;
    return new Promise<LazDecodeSuccess>((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      const request: LazDecodeRequest = { id, buffer, ...options };
      this.worker.postMessage(request, [buffer]);
    });
  }

  dispose() {
    this.worker.terminate();
    const reason = new Error("Point-cloud decoding was canceled.");
    for (const request of this.pending.values()) request.reject(reason);
    this.pending.clear();
  }
}
