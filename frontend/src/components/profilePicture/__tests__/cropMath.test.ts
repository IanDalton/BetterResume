import { describe, expect, it } from 'vitest';
import { EDITOR_SIZE, MAX_ZOOM, MIN_ZOOM, calculatePlacement, clamp, zoomAroundAnchor } from '../cropMath';

describe('clamp', () => {
  it('passes values already inside the range through unchanged', () => {
    expect(clamp(5, 0, 10)).toBe(5);
  });

  it('clamps to the lower and upper bounds', () => {
    expect(clamp(-5, 0, 10)).toBe(0);
    expect(clamp(15, 0, 10)).toBe(10);
  });
});

describe('calculatePlacement', () => {
  it('covers the target square at zoom=1 with no offset', () => {
    // 400x200 landscape image into a 320 square: cover scale is 320/200=1.6,
    // so it draws 640 wide x 320 tall, centered horizontally (dx negative).
    const p = calculatePlacement(400, 200, EDITOR_SIZE, 1, 0, 0);
    expect(p.drawWidth).toBeCloseTo(640);
    expect(p.drawHeight).toBeCloseTo(320);
    expect(p.dy).toBeCloseTo(0);
    expect(p.dx).toBeCloseTo((320 - 640) / 2);
    expect(p.offsetX).toBe(0);
    expect(p.offsetY).toBe(0);
  });

  it('scales draw size up with zoom and grows the shift bounds', () => {
    const p1 = calculatePlacement(400, 200, EDITOR_SIZE, 1, 0, 0);
    const p2 = calculatePlacement(400, 200, EDITOR_SIZE, 2, 0, 0);
    expect(p2.drawWidth).toBeCloseTo(p1.drawWidth * 2);
    expect(p2.drawHeight).toBeCloseTo(p1.drawHeight * 2);
    expect(p2.maxShiftX).toBeGreaterThan(p1.maxShiftX);
    expect(p2.maxShiftY).toBeGreaterThan(p1.maxShiftY);
  });

  it('clamps offsets to the max shift bounds instead of overflowing', () => {
    const p = calculatePlacement(400, 200, EDITOR_SIZE, 2, 10000, -10000);
    expect(p.offsetX).toBeCloseTo(p.maxShiftX);
    expect(p.offsetY).toBeCloseTo(-p.maxShiftY);
  });

  it('never shifts a square image (no slack in either axis at zoom=1)', () => {
    const p = calculatePlacement(300, 300, EDITOR_SIZE, 1, 50, 50);
    expect(p.maxShiftX).toBe(0);
    expect(p.maxShiftY).toBe(0);
    expect(p.offsetX).toBe(0);
    expect(p.offsetY).toBe(0);
  });
});

describe('zoomAroundAnchor', () => {
  const editor = { dataUrl: '', width: 400, height: 400 };

  it('clamps the target zoom to [MIN_ZOOM, MAX_ZOOM]', () => {
    const tooLow = zoomAroundAnchor(editor, { zoom: MIN_ZOOM, offsetX: 0, offsetY: 0 }, MIN_ZOOM - 5);
    expect(tooLow.zoom).toBe(MIN_ZOOM);
    const tooHigh = zoomAroundAnchor(editor, { zoom: MIN_ZOOM, offsetX: 0, offsetY: 0 }, MAX_ZOOM + 5);
    expect(tooHigh.zoom).toBe(MAX_ZOOM);
  });

  it('is a no-op when the target zoom (after clamping) matches the current zoom', () => {
    const prev = { zoom: 1.5, offsetX: 3, offsetY: -4 };
    expect(zoomAroundAnchor(editor, prev, 1.5)).toBe(prev);
  });

  it('keeps the anchor point visually fixed on screen after zooming in', () => {
    const anchor = { x: EDITOR_SIZE / 4, y: EDITOR_SIZE / 4 };
    const prev = { zoom: 1, offsetX: 0, offsetY: 0 };
    const next = zoomAroundAnchor(editor, prev, 2, anchor);

    const before = calculatePlacement(editor.width, editor.height, EDITOR_SIZE, prev.zoom, prev.offsetX, prev.offsetY);
    const after = calculatePlacement(editor.width, editor.height, EDITOR_SIZE, next.zoom, next.offsetX, next.offsetY);

    // The image-space fraction under the anchor should be the same before and after.
    const originXBefore = (anchor.x - before.dx) / before.drawWidth;
    const originYBefore = (anchor.y - before.dy) / before.drawHeight;
    const originXAfter = (anchor.x - after.dx) / after.drawWidth;
    const originYAfter = (anchor.y - after.dy) / after.drawHeight;

    expect(originXAfter).toBeCloseTo(originXBefore, 5);
    expect(originYAfter).toBeCloseTo(originYBefore, 5);
  });

  it('defaults the anchor to the editor center when none is given', () => {
    const prev = { zoom: 1, offsetX: 0, offsetY: 0 };
    const withCenterAnchor = zoomAroundAnchor(editor, prev, 2, { x: EDITOR_SIZE / 2, y: EDITOR_SIZE / 2 });
    const withNoAnchor = zoomAroundAnchor(editor, prev, 2);
    expect(withNoAnchor.offsetX).toBeCloseTo(withCenterAnchor.offsetX, 5);
    expect(withNoAnchor.offsetY).toBeCloseTo(withCenterAnchor.offsetY, 5);
  });

  it('clamps the resulting offsets within the new zoom level bounds', () => {
    // Anchor at the extreme corner while zooming out heavily should still land
    // within the (possibly zero, for a square image at zoom=1) shift bounds.
    const prev = { zoom: MAX_ZOOM, offsetX: 0, offsetY: 0 };
    const next = zoomAroundAnchor(editor, prev, MIN_ZOOM, { x: 0, y: 0 });
    const placement = calculatePlacement(editor.width, editor.height, EDITOR_SIZE, next.zoom, next.offsetX, next.offsetY);
    expect(Math.abs(next.offsetX)).toBeLessThanOrEqual(placement.maxShiftX + 1e-6);
    expect(Math.abs(next.offsetY)).toBeLessThanOrEqual(placement.maxShiftY + 1e-6);
  });
});
