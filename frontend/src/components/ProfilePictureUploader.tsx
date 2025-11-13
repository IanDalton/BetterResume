import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useI18n } from '../i18n';
import { resolveProfilePictureUrl, uploadProfilePicture } from '../services';

interface ProfilePictureUploaderProps {
  userId: string;
  include: boolean;
  onIncludeChange: (value: boolean) => void;
  imageUrl: string | null;
  onUploaded: (url: string | null) => void;
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

const THUMBNAIL_SIZE = 128;
const EDITOR_SIZE = 320;
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
  const cropAreaRef = useRef<HTMLDivElement | null>(null);
  const pointerPositions = useRef<Map<number, { x: number; y: number }>>(new Map());
  const placementRef = useRef({ offsetX: 0, offsetY: 0, zoom: 1 });

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

  useEffect(() => {
    placementRef.current = { offsetX, offsetY, zoom };
  }, [offsetX, offsetY, zoom]);

  const resetPlacement = useCallback(() => {
    setZoom(1);
    setOffsetX(0);
    setOffsetY(0);
    setDragState(null);
    setPinchState(null);
    pointerPositions.current.clear();
    placementRef.current = { offsetX: 0, offsetY: 0, zoom: 1 };
  }, []);

  const triggerFileSelect = useCallback(() => {
    setStatus(null);
    inputRef.current?.click();
  }, []);

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
    } catch (error: any) {
      const message = error instanceof Error && error.message ? error.message : t('profile.upload.error');
      setStatus(message);
      setEditor(null);
    } finally {
      event.target.value = '';
    }
  };

  const applyZoom = useCallback(
    (targetZoom: number, anchor?: { x: number; y: number }) => {
      if (!editor) return;
      const nextZoom = clamp(targetZoom, 1, 3);
      const prev = placementRef.current;
      if (prev.zoom === nextZoom) {
        return;
      }

      const anchorX = clamp(anchor?.x ?? EDITOR_SIZE / 2, 0, EDITOR_SIZE);
      const anchorY = clamp(anchor?.y ?? EDITOR_SIZE / 2, 0, EDITOR_SIZE);

      const prevPlacement = calculatePlacement(
        editor.width,
        editor.height,
        EDITOR_SIZE,
        prev.zoom,
        prev.offsetX,
        prev.offsetY
      );

      const originX = prevPlacement.drawWidth
        ? clamp((anchorX - prevPlacement.dx) / prevPlacement.drawWidth, 0, 1)
        : 0.5;
      const originY = prevPlacement.drawHeight
        ? clamp((anchorY - prevPlacement.dy) / prevPlacement.drawHeight, 0, 1)
        : 0.5;

      const baseScale = Math.max(EDITOR_SIZE / editor.width, EDITOR_SIZE / editor.height);
      const nextDrawWidth = editor.width * baseScale * nextZoom;
      const nextDrawHeight = editor.height * baseScale * nextZoom;

      const desiredOffsetX =
        anchorX - (EDITOR_SIZE - nextDrawWidth) / 2 - originX * nextDrawWidth;
      const desiredOffsetY =
        anchorY - (EDITOR_SIZE - nextDrawHeight) / 2 - originY * nextDrawHeight;

      const nextPlacement = calculatePlacement(
        editor.width,
        editor.height,
        EDITOR_SIZE,
        nextZoom,
        desiredOffsetX,
        desiredOffsetY
      );

      placementRef.current = {
        offsetX: nextPlacement.offsetX,
        offsetY: nextPlacement.offsetY,
        zoom: nextZoom,
      };
      setOffsetX(nextPlacement.offsetX);
      setOffsetY(nextPlacement.offsetY);
      setZoom(nextZoom);
    },
    [editor]
  );

  const editorPlacement = useMemo(() => {
    if (!editor) return null;
    return calculatePlacement(editor.width, editor.height, EDITOR_SIZE, zoom, offsetX, offsetY);
  }, [editor, zoom, offsetX, offsetY]);

  const isDragging = dragState !== null;

  const handlePointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!editor || !editorPlacement) return;
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
        baseOffsetX: placementRef.current.offsetX,
        baseOffsetY: placementRef.current.offsetY,
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
          baseZoom: placementRef.current.zoom,
        });
      }
      setDragState(null);
    }
  };

  const handlePointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!editor || !editorPlacement) return;
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
          const rect = event.currentTarget.getBoundingClientRect();
          const midX = (positions[0].x + positions[1].x) / 2;
          const midY = (positions[0].y + positions[1].y) / 2;
          applyZoom(
            pinchState.baseZoom * (distance / pinchState.startDistance),
            {
              x: clamp(midX - rect.left, 0, EDITOR_SIZE),
              y: clamp(midY - rect.top, 0, EDITOR_SIZE),
            }
          );
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
      -editorPlacement.maxShiftX,
      editorPlacement.maxShiftX
    );
    const nextOffsetY = clamp(
      dragState.baseOffsetY + deltaY,
      -editorPlacement.maxShiftY,
      editorPlacement.maxShiftY
    );
    placementRef.current = { ...placementRef.current, offsetX: nextOffsetX, offsetY: nextOffsetY };
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
        baseOffsetX: placementRef.current.offsetX,
        baseOffsetY: placementRef.current.offsetY,
      });
    }
  };

  const handleWheel = (event: React.WheelEvent<HTMLDivElement>) => {
    if (!editor) return;
    event.preventDefault();
    const rect = event.currentTarget.getBoundingClientRect();
    const factor = Math.exp(-event.deltaY / 300);
    applyZoom(placementRef.current.zoom * factor, {
      x: clamp(event.clientX - rect.left, 0, EDITOR_SIZE),
      y: clamp(event.clientY - rect.top, 0, EDITOR_SIZE),
    });
  };

  const handleUpload = async () => {
    if (!editor) return;
    setUploading(true);
    setStatus(null);
    try {
      const processedFile = await exportEditedImage(editor, shape, zoom, offsetX, offsetY);
      await uploadProfilePicture(userId, processedFile);
      const refreshedUrl = await resolveProfilePictureUrl(userId);
      if (!refreshedUrl) {
        throw new Error(t('profile.upload.refreshError'));
      }
      setStatus(t('profile.upload.success'));
      setEditor(null);
      resetPlacement();
      onUploaded(refreshedUrl);
    } catch (error: any) {
      const message = error instanceof Error && error.message ? error.message : t('profile.upload.error');
      setStatus(message);
    } finally {
      setUploading(false);
    }
  };

  const handleCancel = useCallback(() => {
    setEditor(null);
    resetPlacement();
  }, [resetPlacement]);

  useEffect(() => {
    if (!editor) {
      return;
    }
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        handleCancel();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [editor, handleCancel]);

  const successMessage = t('profile.upload.success');
  const statusTone = status ? (status === successMessage ? 'success' : 'error') : null;

  return (
    <section className="mb-10">
      <h2 className="text-xl font-semibold mb-4">{t('profile.section.title')}</h2>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
        <div className="flex flex-col items-center gap-3">
          <div
            className="relative flex items-center justify-center overflow-hidden rounded-lg border border-neutral-300 bg-neutral-100 text-neutral-500 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-400"
            style={{ width: THUMBNAIL_SIZE, height: THUMBNAIL_SIZE }}
          >
            {imageUrl ? (
              <img src={imageUrl} alt={t('profile.section.title')} className="h-full w-full object-cover" />
            ) : (
              <span className="px-2 text-center text-xs">{t('profile.none')}</span>
            )}
          </div>
          <button type="button" className="btn-secondary btn-sm" onClick={triggerFileSelect} disabled={uploading}>
            {t('profile.upload')}
          </button>
        </div>
        <div className="flex-1 space-y-2 text-sm text-neutral-600 dark:text-neutral-300">
          <p className="text-xs text-neutral-500 dark:text-neutral-400">{t('profile.upload.hint')}</p>
          <label className="flex items-center gap-2 text-xs">
            <input
              type="checkbox"
              className="h-4 w-4"
              checked={include && !!imageUrl}
              onChange={e => onIncludeChange(e.target.checked)}
              disabled={!imageUrl}
            />
            <span className={!imageUrl ? 'text-neutral-400 dark:text-neutral-600' : ''}>{t('profile.toggle')}</span>
          </label>
          {!imageUrl && (
            <p className="text-xs text-neutral-500 dark:text-neutral-500">{t('profile.toggle.disabled')}</p>
          )}
          {status && !editor && (
            <p
              className={`text-xs ${
                statusTone === 'success'
                  ? 'text-green-600 dark:text-green-400'
                  : 'text-red-500 dark:text-red-400'
              }`}
            >
              {status}
            </p>
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

      {editor && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4 py-8"
          onClick={handleCancel}
        >
          <div
            className="relative w-full max-w-2xl overflow-hidden rounded-2xl border border-neutral-200 bg-white shadow-xl dark:border-neutral-700 dark:bg-neutral-900"
            onClick={event => event.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-neutral-200 px-6 py-4 dark:border-neutral-800">
              <div>
                <h3 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100">
                  {t('profile.editing.modalTitle')}
                </h3>
                <p className="text-xs text-neutral-500 dark:text-neutral-400">{t('profile.editing.subtitle')}</p>
              </div>
              <button
                type="button"
                onClick={handleCancel}
                className="rounded-full p-2 text-neutral-500 transition hover:bg-neutral-100 hover:text-neutral-700 focus:outline-none focus:ring-2 focus:ring-red-500 dark:text-neutral-400 dark:hover:bg-neutral-800 dark:hover:text-neutral-200"
                aria-label={t('profile.editing.cancel')}
              >
                <span className="block h-4 w-4">×</span>
              </button>
            </div>
            <div className="flex flex-col gap-6 px-6 py-6">
              <div className="flex flex-col items-center gap-4">
                <div className="relative" style={{ width: EDITOR_SIZE, height: EDITOR_SIZE }}>
                  <div
                    ref={cropAreaRef}
                    className={`relative h-full w-full overflow-hidden bg-neutral-900/80 ${
                      shape === 'circle' ? 'rounded-full' : 'rounded-[28px]'
                    }`}
                    style={{
                      cursor: isDragging ? 'grabbing' : 'grab',
                      touchAction: 'none',
                    }}
                    onPointerDown={handlePointerDown}
                    onPointerMove={handlePointerMove}
                    onPointerUp={endPointerInteraction}
                    onPointerCancel={endPointerInteraction}
                    onPointerLeave={endPointerInteraction}
                    onWheel={handleWheel}
                  >
                    {editorPlacement && (
                      <img
                        src={editor.dataUrl}
                        alt={t('profile.section.title')}
                        className="pointer-events-none select-none"
                        style={{
                          position: 'absolute',
                          width: editorPlacement.drawWidth,
                          height: editorPlacement.drawHeight,
                          left: editorPlacement.dx,
                          top: editorPlacement.dy,
                        }}
                      />
                    )}
                  </div>
                  <div
                    className={`pointer-events-none absolute inset-0 ${
                      shape === 'circle' ? 'rounded-full' : 'rounded-[28px]'
                    }`}
                    style={{ boxShadow: '0 0 0 9999px rgba(0,0,0,0.45)' }}
                  />
                  <div
                    className={`pointer-events-none absolute inset-0 border border-white/80 ${
                      shape === 'circle' ? 'rounded-full' : 'rounded-[28px]'
                    }`}
                  />
                </div>
                <p className="text-xs text-neutral-500 dark:text-neutral-400">{t('profile.editing.gestureHint')}</p>
              </div>

              <div className="space-y-4">
                <div className="flex flex-col gap-3">
                  <div className="flex items-center gap-3 text-xs text-neutral-600 dark:text-neutral-300">
                    <span className="font-medium uppercase tracking-wide text-[11px]">
                      {t('profile.editing.zoom')}
                    </span>
                    <button
                      type="button"
                      className="rounded-full border border-neutral-200 px-2 py-1 text-sm font-medium text-neutral-600 transition hover:border-neutral-300 hover:text-neutral-800 focus:outline-none focus:ring-2 focus:ring-red-500 disabled:opacity-50 dark:border-neutral-700 dark:text-neutral-300 dark:hover:border-neutral-500 dark:hover:text-neutral-100"
                      onClick={() => applyZoom(placementRef.current.zoom - 0.05, {
                        x: EDITOR_SIZE / 2,
                        y: EDITOR_SIZE / 2,
                      })}
                      disabled={placementRef.current.zoom <= 1}
                      aria-label={t('profile.editing.zoomOut')}
                    >
                      −
                    </button>
                    <input
                      type="range"
                      min={100}
                      max={300}
                      step={1}
                      value={Math.round(zoom * 100)}
                      onChange={event => applyZoom(Number(event.target.value) / 100, {
                        x: EDITOR_SIZE / 2,
                        y: EDITOR_SIZE / 2,
                      })}
                      className="flex-1 accent-red-500"
                    />
                    <button
                      type="button"
                      className="rounded-full border border-neutral-200 px-2 py-1 text-sm font-medium text-neutral-600 transition hover:border-neutral-300 hover:text-neutral-800 focus:outline-none focus:ring-2 focus:ring-red-500 disabled:opacity-50 dark:border-neutral-700 dark:text-neutral-300 dark:hover:border-neutral-500 dark:hover:text-neutral-100"
                      onClick={() => applyZoom(placementRef.current.zoom + 0.05, {
                        x: EDITOR_SIZE / 2,
                        y: EDITOR_SIZE / 2,
                      })}
                      disabled={placementRef.current.zoom >= 3}
                      aria-label={t('profile.editing.zoomIn')}
                    >
                      +
                    </button>
                    <span className="w-12 text-right text-[11px] text-neutral-500 dark:text-neutral-400">
                      {Math.round(zoom * 100)}%
                    </span>
                  </div>
                  <div className="flex flex-wrap items-center gap-2 text-xs text-neutral-600 dark:text-neutral-300">
                    <span className="font-medium uppercase tracking-wide text-[11px]">
                      {t('profile.editing.shapeLabel')}
                    </span>
                    <button
                      type="button"
                      className={`btn-tertiary btn-xs ${
                        shape === 'square' ? 'border border-red-500 text-red-600 dark:border-red-400 dark:text-red-300' : ''
                      }`}
                      onClick={() => setShape('square')}
                    >
                      {t('profile.shape.square')}
                    </button>
                    <button
                      type="button"
                      className={`btn-tertiary btn-xs ${
                        shape === 'circle' ? 'border border-red-500 text-red-600 dark:border-red-400 dark:text-red-300' : ''
                      }`}
                      onClick={() => setShape('circle')}
                    >
                      {t('profile.shape.circle')}
                    </button>
                    <div className="ml-auto">
                      <button type="button" className="btn-tertiary btn-xs" onClick={resetPlacement}>
                        {t('profile.editing.reset')}
                      </button>
                    </div>
                  </div>
                </div>
                {status && statusTone === 'error' && (
                  <p className="text-xs text-red-500 dark:text-red-400">{status}</p>
                )}
              </div>

              <div className="flex flex-col-reverse gap-3 border-t border-neutral-200 pt-4 text-sm sm:flex-row sm:justify-end dark:border-neutral-800">
                <button
                  type="button"
                  className="btn-tertiary btn-sm"
                  onClick={handleCancel}
                  disabled={uploading}
                >
                  {t('profile.editing.cancel')}
                </button>
                <button
                  type="button"
                  className="btn-primary btn-sm"
                  onClick={handleUpload}
                  disabled={uploading}
                >
                  {uploading ? t('profile.uploading') : t('profile.editing.save')}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </section>
  );
};
