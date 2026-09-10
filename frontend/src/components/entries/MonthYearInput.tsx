import React, { useMemo, useState } from 'react';
import { Select } from '../ui';
import { useI18n } from '../../i18n';
import { formatMonthYear, isPresent, monthOptions, parseMonthYear, yearOptions } from './monthYear';

export interface MonthYearInputProps {
  value?: string;
  onChange: (v: string) => void;
  allowPresent?: boolean;
  presentLabel?: string;
  invalid?: boolean;
}

/**
 * Month + year selects storing `MM/YYYY`. Two selects instead of `<input type="month">`
 * because that control is missing on desktop Safari (falls back to free text that was
 * silently discarded) and renders as "-------- ----" in localized Chrome.
 */
export const MonthYearInput: React.FC<MonthYearInputProps> = ({
  value,
  onChange,
  allowPresent,
  presentLabel,
  invalid,
}) => {
  const { t, lang } = useI18n();
  const present = !!allowPresent && isPresent(value);
  const parsed = parseMonthYear(value);
  // Half-filled state (one select chosen, the other not yet) lives here; the entry only
  // receives a value once both halves are set.
  const [partial, setPartial] = useState<{ month: string; year: string }>({ month: '', year: '' });
  const month = present ? '' : parsed ? parsed.month : partial.month;
  const year = present ? '' : parsed ? parsed.year : partial.year;

  // Remember the last real date so unchecking "Current" restores it instead of
  // clearing the field — checking it experimentally shouldn't lose prior input.
  const lastDateRef = React.useRef<string>(present ? '' : value || '');
  if (!present && value) lastDateRef.current = value;

  const months = useMemo(() => monthOptions(lang), [lang]);
  const years = useMemo(() => yearOptions(new Date(), 60, year), [year]);

  const update = (m: string, y: string) => {
    setPartial({ month: m, year: y });
    onChange(formatMonthYear(m, y));
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Select
        options={months}
        value={month}
        placeholder={t('date.month')}
        aria-label={t('date.month')}
        onValueChange={(v) => update(v, year)}
        disabled={present}
        invalid={invalid}
        className="min-w-[8.5rem] flex-1"
      />
      <Select
        options={years}
        value={year}
        placeholder={t('date.year')}
        aria-label={t('date.year')}
        onValueChange={(v) => update(month, v)}
        disabled={present}
        invalid={invalid}
        className="w-[6.5rem]"
      />
      {allowPresent && (
        <label className="flex min-h-[44px] shrink-0 items-center gap-2 text-sm text-neutral-700 dark:text-neutral-300">
          <input
            type="checkbox"
            className="h-4 w-4 accent-red-600"
            checked={present}
            onChange={(e) => onChange(e.target.checked ? 'present' : lastDateRef.current)}
          />
          {presentLabel ?? t('present')}
        </label>
      )}
    </div>
  );
};
