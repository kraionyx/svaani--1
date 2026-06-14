// Minimal toast pub-sub so any module can surface a message without prop-drilling.
type Sub = (msg: string, err: boolean) => void;
let sub: Sub | null = null;
export const onToast = (s: Sub) => { sub = s; };
export const toast = (msg: string, err = false) => sub?.(msg, err);
