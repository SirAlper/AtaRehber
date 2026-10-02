// What the animated background follows: whether the assistant is working on an answer (set by the chat), and
// whether the landing page is shown (its backdrop is a lava lamp). The background reads both every frame, so they
// are plain module values instead of React state (no re-render of the page per change).

let thinking = false;
let landing = false;

export function setThinking(value: boolean) {
  thinking = value;
}

export function isThinking() {
  return thinking;
}

export function setLanding(value: boolean) {
  landing = value;
}

export function isLanding() {
  return landing;
}
