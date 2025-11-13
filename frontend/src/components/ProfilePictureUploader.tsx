import React, { useMemo, useRef, useState } from 'react';
import { useI18n } from '../i18n';
import { uploadProfilePicture } from '../services';

interface ProfilePictureUploaderProps {
  userId: string;
  include: boolean;
  onIncludeChange: (value: boolean) => void;
  imageUrl: string | null;
  onUploaded: () => void;
}

type ProfileShape = 'square' | 'circle';

interface EditorState {
  dataUrl: string;
  width: number;
  height: number;
}

interface Placement {
  drawWidth: number;
  drawHeight: number;
  dx: number;
  dy: number;
  maxShiftX: number;
  maxShiftY: number;
  offsetX: number;
  offsetY: number;
}

const PREVIEW_SIZE = 128;
const EXPORT_SIZE = 512;

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function calculatePlacement(
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

async function loadImageFromDataUrl(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('Failed to load image'));
    img.src = src;
  });
}

async function createEditorState(file: File): Promise<EditorState> {
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

async function exportEditedImage(
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
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, EXPORT_SIZE, EXPORT_SIZE);
  } else {
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, EXPORT_SIZE, EXPORT_SIZE);
  }

  const offsetScale = EXPORT_SIZE / PREVIEW_SIZE;
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
      const outputFile = new File([blob], 'profile.png', { type: 'image/png' });
      resolve(outputFile);
    }, 'image/png');
  });
}

export const ProfilePictureUploader: React.FC<ProfilePictureUploaderProps> = ({
  userId,
  include,
  onIncludeChange,
  imageUrl,
  onUploaded,
}) => {
  const { t } = useI18n();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const pointerPositions = useRef<Map<number, { x: number; y: number }>>(new Map());
  const [uploading, setUploading] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [zoom, setZoom] = useState(1);
  const [offsetX, setOffsetX] = useState(0);
  const [offsetY, setOffsetY] = useState(0);
  const [shape, setShape] = useState<ProfileShape>('square');
  const [dragState, setDragState] = useState<{
    pointerId: number;
    startX: number;
    startY: number;
    baseOffsetX: number;
    baseOffsetY: number;
  } | null>(null);
  const [pinchState, setPinchState] = useState<{
    pointerIds: number[];
    startDistance: number;
    baseZoom: number;
  } | null>(null);

  const applyZoom = (targetZoom: number) => {
    if (!editor) return;
    setZoom(prevZoom => {
      const nextZoom = clamp(targetZoom, 1, 3);
      if (prevZoom === nextZoom) {
        return prevZoom;
      }
      const ratio = nextZoom / prevZoom;
      const baseScale = Math.max(PREVIEW_SIZE / editor.width, PREVIEW_SIZE / editor.height);
      const drawWidth = editor.width * baseScale * nextZoom;
      const drawHeight = editor.height * baseScale * nextZoom;
      const maxShiftX = Math.max(0, (drawWidth - PREVIEW_SIZE) / 2);
      const maxShiftY = Math.max(0, (drawHeight - PREVIEW_SIZE) / 2);
      setOffsetX(prevOffset => clamp(prevOffset * ratio, -maxShiftX, maxShiftX));
      setOffsetY(prevOffset => clamp(prevOffset * ratio, -maxShiftY, maxShiftY));
      return nextZoom;
    });
  };

  const resetPlacement = () => {
    setZoom(1);
    setOffsetX(0);
    setOffsetY(0);
    setDragState(null);
    setPinchState(null);
    pointerPositions.current.clear();
  };

  const triggerFileSelect = () => {
    setStatus(null);
    inputRef.current?.click();
  };

  const handleFileChange = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) {
      setStatus(t('profile.error.size'));
      event.target.value = '';
      return;
    }
    setStatus(null);
    try {
      const prepared = await createEditorState(file);
      setEditor(prepared);
      resetPlacement();
      setShape('square');
      setStatus(t('profile.editing.ready'));
    } catch (error: any) {
      const message = error instanceof Error && error.message ? error.message : t('profile.upload.error');
      setStatus(message);
      setEditor(null);
    } finally {
      event.target.value = '';
    }
  };

  const previewPlacement = useMemo(() => {
    if (!editor) return null;
    return calculatePlacement(editor.width, editor.height, PREVIEW_SIZE, zoom, offsetX, offsetY);
  }, [editor, zoom, offsetX, offsetY]);

  const isDragging = dragState !== null;

  const handlePointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!editor || !previewPlacement) return;
    event.preventDefault();
    pointerPositions.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {}

    if (pointerPositions.current.size === 1) {
      setDragState({
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        baseOffsetX: offsetX,
        baseOffsetY: offsetY,
      });
    } else if (pointerPositions.current.size === 2) {
      const entries = Array.from(pointerPositions.current.entries());
      const distance = Math.hypot(
        entries[0][1].x - entries[1][1].x,
        entries[0][1].y - entries[1][1].y
      );
      if (distance > 0) {
        setPinchState({
          pointerIds: entries.map(([id]) => id),
          startDistance: distance,
          baseZoom: zoom,
        });
      }
      setDragState(null);
    }
  };

  const handlePointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!editor || !previewPlacement) return;
    if (pointerPositions.current.has(event.pointerId)) {
      pointerPositions.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
    }

    if (pinchState && pinchState.pointerIds.includes(event.pointerId)) {
      const positions = pinchState.pointerIds
        .map(id => pointerPositions.current.get(id))
        .filter((value): value is { x: number; y: number } => !!value);
      if (positions.length === 2) {
        const distance = Math.hypot(
          positions[0].x - positions[1].x,
          positions[0].y - positions[1].y
        );
        if (distance > 0) {
          applyZoom(pinchState.baseZoom * (distance / pinchState.startDistance));
        }
      }
      return;
    }

    if (!dragState || dragState.pointerId !== event.pointerId) {
      return;
    }

    event.preventDefault();
    const deltaX = event.clientX - dragState.startX;
    const deltaY = event.clientY - dragState.startY;
    const nextOffsetX = clamp(
      dragState.baseOffsetX + deltaX,
      -previewPlacement.maxShiftX,
      previewPlacement.maxShiftX
    );
    const nextOffsetY = clamp(
      dragState.baseOffsetY + deltaY,
      -previewPlacement.maxShiftY,
      previewPlacement.maxShiftY
    );
    setOffsetX(nextOffsetX);
    setOffsetY(nextOffsetY);
  };

  const endPointerInteraction = (event: React.PointerEvent<HTMLDivElement>) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      try {
        event.currentTarget.releasePointerCapture(event.pointerId);
      } catch {}
    }

    const wasPinching = pinchState && pinchState.pointerIds.includes(event.pointerId);
    if (wasPinching) {
      setPinchState(null);
    }

    pointerPositions.current.delete(event.pointerId);

    if (dragState && dragState.pointerId === event.pointerId) {
      setDragState(null);
    }

    if (wasPinching && pointerPositions.current.size === 1) {
      const [id, position] = Array.from(pointerPositions.current.entries())[0];
      setDragState({
        pointerId: id,
        startX: position.x,
        startY: position.y,
        baseOffsetX: offsetX,
        baseOffsetY: offsetY,
      });
    }
  };

  const handleWheel = (event: React.WheelEvent<HTMLDivElement>) => {
    if (!editor) return;
    event.preventDefault();
    const factor = Math.exp(-event.deltaY / 300);
    applyZoom(zoom * factor);
  };


  const handleUpload = async () => {
    if (!editor) return;
    setUploading(true);
    setStatus(null);
    try {
      const processedFile = await exportEditedImage(editor, shape, zoom, offsetX, offsetY);
      await uploadProfilePicture(userId, processedFile);
      setStatus(t('profile.upload.success'));
      setEditor(null);
      resetPlacement();
      onUploaded();
    } catch (error: any) {
      const message = error instanceof Error && error.message ? error.message : t('profile.upload.error');
      setStatus(message);
    } finally {
      setUploading(false);
    }
  };

  const handleCancel = () => {
    setEditor(null);
    setStatus(null);
    resetPlacement();
  };

  return (
    <section className="mb-10">
      <h2 className="text-xl font-semibold mb-4">{t('profile.section.title')}</h2>
      <div className="flex flex-col sm:flex-row gap-4 sm:items-start">
        <div className="flex flex-col items-center gap-3">
          <div
            className={`relative flex items-center justify-center border border-neutral-300 dark:border-neutral-700 bg-neutral-100 dark:bg-neutral-900 overflow-hidden ${
              editor ? (shape === 'circle' ? 'rounded-full' : 'rounded-lg') : 'rounded-lg'
            }`}
            style={{
              width: PREVIEW_SIZE,
              height: PREVIEW_SIZE,
              cursor: editor ? (isDragging ? 'grabbing' : 'grab') : 'default',
              touchAction: editor ? 'none' : undefined,
            }}
            onPointerDown={editor ? handlePointerDown : undefined}
            onPointerMove={editor ? handlePointerMove : undefined}
            onPointerUp={editor ? endPointerInteraction : undefined}
            onPointerCancel={editor ? endPointerInteraction : undefined}
            onPointerLeave={editor ? endPointerInteraction : undefined}
            onWheel={editor ? handleWheel : undefined}
          >
            {editor && previewPlacement ? (
              <>
                <img
                  src={editor.dataUrl}
                  alt={t('profile.section.title')}
                  style={{
                    position: 'absolute',
                    width: previewPlacement.drawWidth,
                    height: previewPlacement.drawHeight,
                    left: previewPlacement.dx,
                    top: previewPlacement.dy,
                  }}
                />
              </>
            ) : imageUrl ? (
              <img src={imageUrl} alt={t('profile.section.title')} className="w-full h-full object-cover" />
            ) : (
              <span className="text-xs text-neutral-500 text-center px-2">{t('profile.none')}</span>
            )}
          </div>
          {editor && (
            <div className="flex gap-2">
              <button type="button" className="btn-tertiary btn-xs" onClick={handleCancel} disabled={uploading}>
                {t('profile.editing.cancel')}
              </button>
              <button type="button" className="btn-primary btn-xs" onClick={handleUpload} disabled={uploading}>
                {uploading ? t('profile.uploading') : t('profile.editing.save')}
              </button>
            </div>
          )}
        </div>
        <div className="flex-1 flex flex-col gap-2">
          <div className="flex flex-wrap gap-2 items-center">
            <button type="button" className="btn-secondary btn-sm" onClick={triggerFileSelect} disabled={uploading}>
              {t('profile.upload')}
            </button>
            <label className="flex items-center gap-2 text-sm text-neutral-700 dark:text-neutral-300">
              <input
                type="checkbox"
                className="h-4 w-4"
                checked={include && !!imageUrl}
                onChange={e => onIncludeChange(e.target.checked)}
                disabled={!imageUrl}
              />
              <span>{t('profile.toggle')}</span>
            </label>
          </div>
          <p className="text-xs text-neutral-500 dark:text-neutral-400">{t('profile.upload.hint')}</p>
          {!imageUrl && (
            <p className="text-xs text-neutral-500 dark:text-neutral-500">{t('profile.toggle.disabled')}</p>
          )}
          {editor && (
            <div className="mt-2 space-y-3 rounded-md border border-dashed border-neutral-300 dark:border-neutral-700 bg-neutral-50/70 dark:bg-neutral-900/40 p-3">
              <p className="text-xs text-neutral-600 dark:text-neutral-300">{t('profile.editing.instructions')}</p>
              <label className="flex flex-col gap-1 text-xs text-neutral-600 dark:text-neutral-300">
                <span className="font-medium">{t('profile.editing.zoom')}</span>
                <input
                  type="range"
                  min={100}
                  max={300}
                  step={5}
                  value={Math.round(zoom * 100)}
                  onChange={e => applyZoom(Number(e.target.value) / 100)}
                />
              </label>
              <p className="text-xs text-neutral-500 dark:text-neutral-400">{t('profile.editing.gestureHint')}</p>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  className="btn-tertiary btn-xs"
                  onClick={resetPlacement}
                >
                  {t('profile.editing.reset')}
                </button>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  className={`btn-tertiary btn-xs ${shape === 'square' ? 'border border-red-500 text-red-600 dark:text-red-400' : ''}`}
                  onClick={() => setShape('square')}
                >
                  {t('profile.shape.square')}
                </button>
                <button
                  type="button"
                  className={`btn-tertiary btn-xs ${shape === 'circle' ? 'border border-red-500 text-red-600 dark:text-red-400' : ''}`}
                  onClick={() => setShape('circle')}
                >
                  {t('profile.shape.circle')}
                </button>
              </div>
            </div>
          )}
          {status && (
            <p className="text-xs text-neutral-500 dark:text-neutral-400">{status}</p>
          )}
        </div>
      </div>
      <input
        ref={inputRef}
        type="file"
        accept="image/png,image/jpeg"
        className="hidden"
        onChange={handleFileChange}
      />
    </section>
  );
};
