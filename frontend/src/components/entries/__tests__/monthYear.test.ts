import { describe, expect, it } from 'vitest';
import { formatMonthYear, isPresent, monthOptions, parseMonthYear, yearOptions } from '../monthYear';

describe('parseMonthYear', () => {
  it('splits a stored MM/YYYY value into its selects', () => {
    expect(parseMonthYear('03/2020')).toEqual({ month: '03', year: '2020' });
    expect(parseMonthYear(' 12/1999 ')).toEqual({ month: '12', year: '1999' });
  });

  it('rejects anything that is not MM/YYYY', () => {
    expect(parseMonthYear('')).toBeNull();
    expect(parseMonthYear(undefined)).toBeNull();
    expect(parseMonthYear('present')).toBeNull();
    expect(parseMonthYear('2020-03')).toBeNull();
    expect(parseMonthYear('13/2020')).toBeNull();
    expect(parseMonthYear('3/2020')).toBeNull();
  });
});

describe('formatMonthYear', () => {
  it('builds MM/YYYY once both halves are chosen', () => {
    expect(formatMonthYear('03', '2020')).toBe('03/2020');
    expect(formatMonthYear('3', '2020')).toBe('03/2020');
  });

  it('returns an empty string while a half is missing or malformed', () => {
    expect(formatMonthYear('', '2020')).toBe('');
    expect(formatMonthYear('03', '')).toBe('');
    expect(formatMonthYear('13', '2020')).toBe('');
    expect(formatMonthYear('03', '20')).toBe('');
  });

  it('round-trips with parseMonthYear', () => {
    const parsed = parseMonthYear('07/2015')!;
    expect(formatMonthYear(parsed.month, parsed.year)).toBe('07/2015');
  });
});

describe('isPresent', () => {
  it('is case-insensitive and ignores whitespace', () => {
    expect(isPresent('present')).toBe(true);
    expect(isPresent(' Present ')).toBe(true);
    expect(isPresent('03/2020')).toBe(false);
    expect(isPresent('')).toBe(false);
  });
});

describe('options', () => {
  it('lists twelve localized months with two-digit values', () => {
    const es = monthOptions('es');
    expect(es).toHaveLength(12);
    expect(es[0].value).toBe('01');
    expect(es[11].value).toBe('12');
    expect(es[0].label.toLowerCase()).toContain('enero');
    expect(monthOptions('en')[0].label).toBe('January');
  });

  it('spans next year back sixty years and keeps an out-of-range stored year', () => {
    const years = yearOptions(new Date(2026, 0, 1), 60);
    expect(years[0].value).toBe('2027');
    expect(years).toHaveLength(60);
    expect(years[years.length - 1].value).toBe('1968');
    const withOld = yearOptions(new Date(2026, 0, 1), 60, '1950');
    expect(withOld.map((y) => y.value)).toContain('1950');
    expect(withOld[withOld.length - 1].value).toBe('1950');
  });
});
