/** Number of lines a {@link HeadBuffer} keeps by default. */
export const DEFAULT_HEAD_LINES = 20;

/** Number of lines a {@link TailBuffer} keeps by default. */
export const DEFAULT_TAIL_LINES = 20;

/**
 * Turns a stream of byte or text chunks into complete lines.
 *
 * Lines end with `\n` or `\r\n`; the line end is not part of the line.
 * Multi-byte UTF-8 sequences may be split across chunks. A trailing
 * partial line is held until more input arrives or {@link end} is called.
 */
export class LineSplitter {
  private readonly decoder = new TextDecoder('utf-8');
  private pending = '';

  /**
   * Adds a chunk and returns the lines it completed.
   *
   * @param chunk Raw bytes or already decoded text.
   * @returns Complete lines in order, possibly empty.
   */
  push(chunk: Uint8Array | string): string[] {
    const text = typeof chunk === 'string' ? chunk : this.decoder.decode(chunk, { stream: true });
    return this.take(text);
  }

  /**
   * Flushes the decoder and returns the final partial line, if any.
   *
   * The splitter can be reused afterwards.
   *
   * @returns Zero or one remaining line.
   */
  end(): string[] {
    const rest = this.pending + this.decoder.decode();
    this.pending = '';
    if (rest.length === 0) {
      return [];
    }
    return [stripCarriageReturn(rest)];
  }

  private take(text: string): string[] {
    if (text.length === 0) {
      return [];
    }
    const parts = (this.pending + text).split('\n');
    this.pending = parts.pop() ?? '';
    return parts.map(stripCarriageReturn);
  }
}

/** Keeps the most recent lines, dropping the oldest first. */
export class TailBuffer {
  private readonly kept: string[] = [];

  /**
   * Creates a buffer.
   *
   * @param capacity Maximum number of lines kept.
   */
  constructor(private readonly capacity: number = DEFAULT_TAIL_LINES) {}

  /**
   * Adds lines in arrival order.
   *
   * @param lines Lines to append.
   */
  add(lines: readonly string[]): void {
    this.kept.push(...lines);
    if (this.kept.length > this.capacity) {
      this.kept.splice(0, this.kept.length - this.capacity);
    }
  }

  /**
   * Returns the kept lines, oldest first.
   *
   * @returns A copy of the kept lines.
   */
  lines(): string[] {
    return [...this.kept];
  }
}

/** Keeps the first lines and ignores everything after them. */
export class HeadBuffer {
  private readonly kept: string[] = [];

  /**
   * Creates a buffer.
   *
   * @param capacity Maximum number of lines kept.
   */
  constructor(private readonly capacity: number = DEFAULT_HEAD_LINES) {}

  /**
   * Adds lines in arrival order until the buffer is full.
   *
   * @param lines Lines to append.
   */
  add(lines: readonly string[]): void {
    for (const line of lines) {
      if (this.kept.length >= this.capacity) {
        return;
      }
      this.kept.push(line);
    }
  }

  /**
   * Returns the kept lines, oldest first.
   *
   * @returns A copy of the kept lines.
   */
  lines(): string[] {
    return [...this.kept];
  }
}

/**
 * Holds the first and the last lines of a process's stderr.
 *
 * The head shows why a Server failed to start; the tail shows why it
 * stopped. The two overlap while the output is short.
 */
export class StderrCapture {
  private readonly head: HeadBuffer;
  private readonly tail: TailBuffer;
  private count = 0;

  /**
   * Creates a capture.
   *
   * @param headLines Number of leading lines kept.
   * @param tailLines Number of trailing lines kept.
   */
  constructor(headLines: number = DEFAULT_HEAD_LINES, tailLines: number = DEFAULT_TAIL_LINES) {
    this.head = new HeadBuffer(headLines);
    this.tail = new TailBuffer(tailLines);
  }

  /**
   * Adds lines in arrival order.
   *
   * @param lines Lines to record.
   */
  add(lines: readonly string[]): void {
    this.head.add(lines);
    this.tail.add(lines);
    this.count += lines.length;
  }

  /**
   * Returns the first lines.
   *
   * @returns A copy of the head lines, oldest first.
   */
  headLines(): string[] {
    return this.head.lines();
  }

  /**
   * Returns the last lines.
   *
   * @returns A copy of the tail lines, oldest first.
   */
  tailLines(): string[] {
    return this.tail.lines();
  }

  /**
   * Returns the number of lines added, including those no longer kept.
   *
   * @returns The total line count.
   */
  totalLines(): number {
    return this.count;
  }
}

function stripCarriageReturn(line: string): string {
  return line.endsWith('\r') ? line.slice(0, -1) : line;
}
