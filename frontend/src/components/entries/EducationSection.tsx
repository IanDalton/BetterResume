import React from 'react';
import { EDUCATION_TYPES, ResumeEntry } from '../../types';
import { FormField, Input, Textarea, Select } from '../ui';
import { EntrySectionCard } from './EntrySectionCard';
import { MonthYearInput } from './MonthYearInput';
import { educationEntrySchema } from './validation';
import { useI18n } from '../../i18n';

interface Props {
  entries: ResumeEntry[];
  onAdd: (e: ResumeEntry) => void;
  onUpdate: (i: number, e: ResumeEntry) => void;
  onRemove: (i: number) => void;
}

export const EducationSection: React.FC<Props> = ({ entries, onAdd, onUpdate, onRemove }) => {
  const { t } = useI18n();
  const hasAny = entries.some((e) => EDUCATION_TYPES.includes(e.type));
  const typeOptions = [
    { value: 'education', label: t('type.education') },
    { value: 'certification', label: t('field.certification') },
  ];

  return (
    <EntrySectionCard
      title={t('section.education.title')}
      hint={t('section.education.hint')}
      addLabel={t('education.add')}
      emptyLabel={t('entries.none')}
      types={EDUCATION_TYPES}
      defaultType="education"
      entries={entries}
      onAdd={onAdd}
      onUpdate={onUpdate}
      onRemove={onRemove}
      schema={educationEntrySchema}
      isComplete={hasAny}
      renderFields={({ value, setField, errors }) => (
        <>
          <FormField label={t('field.type')}>
            <Select options={typeOptions} value={value.type} onValueChange={(v) => setField('type', v)} />
          </FormField>
          <FormField label={t('education.degree.placeholder')} required error={errors.role}>
            <Input value={value.role} onChange={(e) => setField('role', e.target.value)} invalid={!!errors.role} />
          </FormField>
          <FormField label={t('education.institution.placeholder')} required error={errors.company}>
            <Input value={value.company || ''} onChange={(e) => setField('company', e.target.value)} invalid={!!errors.company} />
          </FormField>
          <FormField label={t('education.location.placeholder')}>
            <Input value={value.location || ''} onChange={(e) => setField('location', e.target.value)} />
          </FormField>
          <FormField label={t('field.start')} error={errors.start}>
            <MonthYearInput value={value.start} onChange={(v) => setField('start', v)} invalid={!!errors.start} />
          </FormField>
          <FormField label={t('field.end')} error={errors.end}>
            <MonthYearInput
              value={value.end}
              onChange={(v) => setField('end', v)}
              allowPresent
              presentLabel={t('present')}
              invalid={!!errors.end}
            />
          </FormField>
          <FormField label={t('education.description.placeholder')} className="sm:col-span-2">
            <Textarea value={value.description || ''} onChange={(e) => setField('description', e.target.value)} />
          </FormField>
        </>
      )}
    />
  );
};
