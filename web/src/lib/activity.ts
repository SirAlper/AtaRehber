// Whether the assistant is working on an answer. The chat sets it; the animated background reads it every frame,
// so it is a plain module value instead of React state (no re-render of the page per change).

let thinking = false;

export function setThinking(value: boolean) {
  thinking = value;
}

export function isThinking() {
  return thinking;
}
