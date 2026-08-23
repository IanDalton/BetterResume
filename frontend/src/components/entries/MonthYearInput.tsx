import React from 'react';
import { Input } from '../ui';

function monthYearToInputValue(v?: string): string {
  if (!v) return '';
  const m = v.match(/^(\d{2})\/(\d{4})$/);
  if (!m) return '';
  return `${m[2]}-${m[1]}`;
}

function inputValueToMonthYear(v: string): string {
  if (!v) return '';
  const [yyyy, mm] = v.split('-');
  if (!yyyy || !mm) return '';
  return `${mm}/${yyyy}`;
}

export interface MonthYearInputProps {
  value?: string;
  onChange: (v: string) => void;
  allowPresent?: boolean;
  presentLabel?: string;
  invalid?: boolean;
}

export const MonthYearInput: React.FC<MonthYearInputProps> = ({
  value,
  onChange,
  allowPresent,
  presentLabel = 'Present',
  invalid,
}) => {
  const isPresent = !!allowPresent && (value || '').toLowerCase() === 'present';
  // Remember the last real date so unchecking "Present" restores it instead of
  // clearing the field — checking it experimentally shouldn't lose prior input.
  const lastDateRef = React.useRef<string>(isPresent ? '' : value || '');
  if (!isPresent && value) lastDateRef.current = value;

  return (
    <div className="flex items-center gap-2">
      <Input
        type="month"
        value={isPresent ? '' : monthYearToInputValue(value)}
        onChange={(e) => onChange(inputValueToMonthYear(e.target.value))}
        disabled={isPresent}
        invalid={invalid}
        className="flex-1"
        // Browsers without a native month picker (e.g. desktop Safari) fall back to a
        // plain text field with no format hint otherwise.
        placeholder="YYYY-MM"
      />
      {allowPresent && (
        <label className="flex shrink-0 items-center gap-1 text-xs text-neutral-600 dark:text-neutral-400">
          <input
            type="checkbox"
            checked={isPresent}
            onChange={(e) => onChange(e.target.checked ? 'present' : lastDateRef.current)}
          />
          {presentLabel}
        </label>
      )}
    </div>
  );
};
