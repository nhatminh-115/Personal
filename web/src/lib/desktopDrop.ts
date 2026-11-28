export interface DesktopDroppedFilePayload {
  name: string;
  mimeType: string;
  bytesBase64: string;
}

export function toDesktopDroppedFile(payload: DesktopDroppedFilePayload): File {
  const binary = atob(payload.bytesBase64);
  const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
  return new File([bytes], payload.name, { type: payload.mimeType });
}
