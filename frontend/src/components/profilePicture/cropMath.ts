/**
 * Pure crop/zoom math and image conversion for the profile photo editor. No React here,
 * so the placement rules can be reasoned about (and tested) on their own.
 */

export type ProfileShape = 'square' | 'circle';

export interface EditorState {
  dataUrl: string;
  width: number;
  height: number;
}

export interface Placement {
  drawWidth: number;
  drawHeight: number;
  dx: number;
  dy: number;
  maxShiftX: number;
  maxShiftY: number;
  offsetX: number;
  offsetY: number;
}

export const EDITOR_SIZE = 320;
export const EXPORT_SIZE = 512;
export const MIN_ZOOM = 1;
export const MAX_ZOOM = 3;

export function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

/** Where to draw the image inside a `targetSize` square so it always covers the square,
 * at `zoom` (1 = cover), shifted by the (clamped) offsets. */
export function calculatePlacement(
  imageWidth: number,
  imageHeight: number,
  targetSize: number,
  zoom: number,
  offsetX: number,
  offsetY: number
): Placement {
  const baseScale = Math.max(targetSize / imageWidth, targetSize / imageHeight);
  const scale = baseScale * zoom;
  const drawWidth = imageWidth * scale;
  const drawHeight = imageHeight * scale;
  const maxShiftX = Math.max(0, (drawWidth - targetSize) / 2);
  const maxShiftY = Math.max(0, (drawHeight - targetSize) / 2);
  const clampedOffsetX = clamp(offsetX, -maxShiftX, maxShiftX);
  const clampedOffsetY = clamp(offsetY, -maxShiftY, maxShiftY);
  const dx = (targetSize - drawWidth) / 2 + clampedOffsetX;
  const dy = (targetSize - drawHeight) / 2 + clampedOffsetY;
  return {
    drawWidth,
    drawHeight,
    dx,
    dy,
    maxShiftX,
    maxShiftY,
    offsetX: clampedOffsetX,
    offsetY: clampedOffsetY,
  };
}

/** Recomputes offsets so that zooming keeps the point under `anchor` (editor
 * coordinates) fixed on screen, then clamps to the new bounds. */
export function zoomAroundAnchor(
  editor: EditorState,
  prev: { zoom: number; offsetX: number; offsetY: number },
  targetZoom: number,
  anchor?: { x: number; y: number }
): { zoom: number; offsetX: number; offsetY: number } {
  const nextZoom = clamp(targetZoom, MIN_ZOOM, MAX_ZOOM);
  if (prev.zoom === nextZoom) return prev;

  const anchorX = clamp(anchor?.x ?? EDITOR_SIZE / 2, 0, EDITOR_SIZE);
  const anchorY = clamp(anchor?.y ?? EDITOR_SIZE / 2, 0, EDITOR_SIZE);

  const prevPlacement = calculatePlacement(editor.width, editor.height, EDITOR_SIZE, prev.zoom, prev.offsetX, prev.offsetY);

  const originX = prevPlacement.drawWidth
    ? clamp((anchorX - prevPlacement.dx) / prevPlacement.drawWidth, 0, 1)
    : 0.5;
  const originY = prevPlacement.drawHeight
    ? clamp((anchorY - prevPlacement.dy) / prevPlacement.drawHeight, 0, 1)
    : 0.5;

  const baseScale = Math.max(EDITOR_SIZE / editor.width, EDITOR_SIZE / editor.height);
  const nextDrawWidth = editor.width * baseScale * nextZoom;
  const nextDrawHeight = editor.height * baseScale * nextZoom;

  const desiredOffsetX = anchorX - (EDITOR_SIZE - nextDrawWidth) / 2 - originX * nextDrawWidth;
  const desiredOffsetY = anchorY - (EDITOR_SIZE - nextDrawHeight) / 2 - originY * nextDrawHeight;

  const next = calculatePlacement(editor.width, editor.height, EDITOR_SIZE, nextZoom, desiredOffsetX, desiredOffsetY);
  return { zoom: nextZoom, offsetX: next.offsetX, offsetY: next.offsetY };
}

export async function loadImageFromDataUrl(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('Failed to load image'));
    img.src = src;
  });
}

export async function createEditorState(file: File): Promise<EditorState> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = async () => {
      try {
        const dataUrl = typeof reader.result === 'string' ? reader.result : '';
        const img = await loadImageFromDataUrl(dataUrl);
        resolve({ dataUrl, width: img.width, height: img.height });
      } catch (err) {
        reject(err);
      }
    };
    reader.onerror = () => reject(new Error('Failed to read image file'));
    reader.readAsDataURL(file);
  });
}

/** Renders the cropped/zoomed/shaped image into a 512px PNG file. */
export async function exportEditedImage(
  editor: EditorState,
  shape: ProfileShape,
  zoom: number,
  offsetX: number,
  offsetY: number
): Promise<File> {
  const img = await loadImageFromDataUrl(editor.dataUrl);
  const canvas = document.createElement('canvas');
  canvas.width = EXPORT_SIZE;
  canvas.height = EXPORT_SIZE;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('Canvas not supported');

  ctx.clearRect(0, 0, EXPORT_SIZE, EXPORT_SIZE);
  if (shape === 'circle') {
    ctx.save();
    ctx.beginPath();
    ctx.arc(EXPORT_SIZE / 2, EXPORT_SIZE / 2, EXPORT_SIZE / 2, 0, Math.PI * 2);
    ctx.closePath();
    ctx.clip();
  }
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, EXPORT_SIZE, EXPORT_SIZE);

  const offsetScale = EXPORT_SIZE / EDITOR_SIZE;
  const placement = calculatePlacement(
    img.width,
    img.height,
    EXPORT_SIZE,
    zoom,
    offsetX * offsetScale,
    offsetY * offsetScale
  );
  ctx.drawImage(img, placement.dx, placement.dy, placement.drawWidth, placement.drawHeight);
  if (shape === 'circle') {
    ctx.restore();
  }

  return new Promise<File>((resolve, reject) => {
    canvas.toBlob(blob => {
      if (!blob) {
        reject(new Error('Failed to prepare image'));
        return;
      }
      resolve(new File([blob], 'profile.png', { type: 'image/png' }));
    }, 'image/png');
  });
}
