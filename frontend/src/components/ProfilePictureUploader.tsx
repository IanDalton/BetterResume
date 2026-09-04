import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useI18n } from '../i18n';
import { resolveProfilePictureUrl, uploadProfilePicture } from '../services';
import { Button, Dialog } from './ui';
import {
  EDITOR_SIZE, MAX_ZOOM, MIN_ZOOM, calculatePlacement, clamp, createEditorState, exportEditedImage,
  zoomAroundAnchor, type EditorState, type ProfileShape,
} from './profilePicture/cropMath';

interface ProfilePictureUploaderProps {
  userId: string;
  imageUrl: string | null;
  onUploaded: (url: string | null) => void;
}

const THUMBNAIL_SIZE = 112;
const MAX_FILE_BYTES = 5 * 1024 * 1024;

/** Profile photo card (one more card in the profile block) plus the crop dialog. */
export const ProfilePictureUploader: React.FC<ProfilePictureUploaderProps> = ({ userId, imageUrl, onUploaded }) => {
  const { t } = useI18n();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const pointerPositions = useRef<Map<number, { x: number; y: number }>>(new Map());
  const placementRef = useRef({ offsetX: 0, offsetY: 0, zoom: 1 });

  const [uploading, setUploading] = useState(false);
  const [status, setStatus] = useState<{ tone: 'success' | 'error'; text: string } | null>(null);
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
    if (file.size > MAX_FILE_BYTES) {
      setStatus({ tone: 'error', text: t('profile.error.size') });
      event.target.value = '';
      return;
    }
    setStatus(null);
    try {
      const prepared = await createEditorState(file);
      setEditor(prepared);
      resetPlacement();
      setShape('square');
    } catch {
      setStatus({ tone: 'error', text: t('profile.upload.error') });
      setEditor(null);
    } finally {
      event.target.value = '';
    }
  };

  const applyZoom = useCallback(
    (targetZoom: number, anchor?: { x: number; y: number }) => {
      if (!editor) return;
      const next = zoomAroundAnchor(editor, placementRef.current, targetZoom, anchor);
      if (next === placementRef.current) return;
      placementRef.current = next;
      setOffsetX(next.offsetX);
      setOffsetY(next.offsetY);
      setZoom(next.zoom);
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
    const nextOffsetX = clamp(dragState.baseOffsetX + deltaX, -editorPlacement.maxShiftX, editorPlacement.maxShiftX);
    const nextOffsetY = clamp(dragState.baseOffsetY + deltaY, -editorPlacement.maxShiftY, editorPlacement.maxShiftY);
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
      if (!refreshedUrl) throw new Error('refresh failed');
      setStatus({ tone: 'success', text: t('profile.upload.success') });
      setEditor(null);
      resetPlacement();
      onUploaded(refreshedUrl);
    } catch {
      setStatus({ tone: 'error', text: t('profile.upload.error') });
    } finally {
      setUploading(false);
    }
  };

  const handleCancel = useCallback(() => {
    if (uploading) return;
    setEditor(null);
    resetPlacement();
  }, [resetPlacement, uploading]);

  const cropRadius = shape === 'circle' ? 'rounded-full' : 'rounded-xl';

  return (
    <div className="rounded-xl border border-neutral-200 bg-white p-5 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
      <div className="mb-3">
        <h3 className="text-base font-semibold text-neutral-900 dark:text-neutral-100">{t('profile.section.title')}</h3>
        <p className="mt-1 text-xs text-neutral-500 dark:text-neutral-400">{t('profile.section.hint')}</p>
      </div>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
        <div className="flex flex-col items-center gap-3">
          <div
            className="relative flex items-center justify-center overflow-hidden rounded-lg border border-neutral-300 bg-neutral-100 text-neutral-500 dark:border-neutral-700 dark:bg-neutral-800 dark:text-neutral-400"
            style={{ width: THUMBNAIL_SIZE, height: THUMBNAIL_SIZE }}
          >
            {imageUrl ? (
              <img src={imageUrl} alt={t('profile.section.title')} className="h-full w-full object-cover" />
            ) : (
              <span className="px-2 text-center text-xs">{t('profile.none')}</span>
            )}
          </div>
          <Button type="button" variant="secondary" size="sm" onClick={triggerFileSelect} disabled={uploading}>
            {t('profile.upload')}
          </Button>
        </div>
        <div className="flex-1 space-y-2 text-sm text-neutral-600 dark:text-neutral-300">
          <p className="text-xs text-neutral-500 dark:text-neutral-400">{t('profile.upload.hint')}</p>
          <p className="max-w-md text-xs text-amber-700 dark:text-amber-400">{t('profile.warning')}</p>
          {status && !editor && (
            <p
              role={status.tone === 'error' ? 'alert' : undefined}
              className={`text-xs ${status.tone === 'success' ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}
            >
              {status.text}
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

      <Dialog
        open={!!editor}
        onOpenChange={(open) => { if (!open) handleCancel(); }}
        size="lg"
        title={t('profile.editing.modalTitle')}
        description={t('profile.editing.subtitle')}
        footer={
          <>
            <Button type="button" variant="secondary" onClick={handleCancel} disabled={uploading}>
              {t('profile.editing.cancel')}
            </Button>
            <Button type="button" loading={uploading} onClick={handleUpload}>
              {uploading ? t('profile.uploading') : t('profile.editing.save')}
            </Button>
          </>
        }
      >
        {editor && (
          <div className="flex flex-col gap-6">
            <div className="flex flex-col items-center gap-4">
              <div className="relative max-w-full" style={{ width: EDITOR_SIZE, height: EDITOR_SIZE }}>
                <div
                  className={`relative h-full w-full overflow-hidden bg-neutral-900/80 ${cropRadius}`}
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
                      className="pointer-events-none select-none max-w-none"
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
                <div className={`pointer-events-none absolute inset-0 border border-white/80 ${cropRadius}`} />
              </div>
              <p className="text-xs text-neutral-500 dark:text-neutral-400">{t('profile.editing.gestureHint')}</p>
            </div>

            <div className="space-y-3">
              <div className="flex items-center gap-3 text-sm text-neutral-700 dark:text-neutral-300">
                <span className="font-medium">{t('profile.editing.zoom')}</span>
                <Button
                  type="button"
                  variant="tertiary"
                  size="xs"
                  onClick={() => applyZoom(placementRef.current.zoom - 0.05)}
                  disabled={zoom <= MIN_ZOOM}
                  aria-label={t('profile.editing.zoomOut')}
                >
                  −
                </Button>
                <input
                  type="range"
                  min={MIN_ZOOM * 100}
                  max={MAX_ZOOM * 100}
                  step={1}
                  value={Math.round(zoom * 100)}
                  onChange={event => applyZoom(Number(event.target.value) / 100)}
                  className="flex-1 accent-red-600"
                  aria-label={t('profile.editing.zoom')}
                />
                <Button
                  type="button"
                  variant="tertiary"
                  size="xs"
                  onClick={() => applyZoom(placementRef.current.zoom + 0.05)}
                  disabled={zoom >= MAX_ZOOM}
                  aria-label={t('profile.editing.zoomIn')}
                >
                  +
                </Button>
                <span className="w-12 text-right text-xs text-neutral-500 dark:text-neutral-400">
                  {Math.round(zoom * 100)}%
                </span>
              </div>
              <div className="flex flex-wrap items-center gap-2 text-sm text-neutral-700 dark:text-neutral-300">
                <span className="font-medium">{t('profile.editing.shapeLabel')}</span>
                <Button type="button" variant="option" size="xs" selected={shape === 'square'} onClick={() => setShape('square')}>
                  {t('profile.shape.square')}
                </Button>
                <Button type="button" variant="option" size="xs" selected={shape === 'circle'} onClick={() => setShape('circle')}>
                  {t('profile.shape.circle')}
                </Button>
                <div className="ml-auto">
                  <Button type="button" variant="tertiary" size="xs" onClick={resetPlacement}>
                    {t('profile.editing.reset')}
                  </Button>
                </div>
              </div>
              {status && status.tone === 'error' && (
                <p className="text-xs text-red-600 dark:text-red-400" role="alert">{status.text}</p>
              )}
            </div>
          </div>
        )}
      </Dialog>
    </div>
  );
};
