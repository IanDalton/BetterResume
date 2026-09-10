import React, { useMemo } from 'react';
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
  const typeOptions = EDUCATION_TYPES.map((v) => ({ value: v, label: t(`type.${v}`) }));
  const schema = useMemo(() => educationEntrySchema(t), [t]);

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
      schema={schema}
      isComplete={hasAny}
      renderFields={({ value, setField, errors }) => (
        <>
          <FormField label={t('field.type')} hint={t('field.type.hint')}>
            <Select options={typeOptions} value={value.type} onValueChange={(v) => setField('type', v)} />
          </FormField>
          <FormField label={t('education.degree')} required error={errors.role}>
            <Input value={value.role} onChange={(e) => setField('role', e.target.value)} invalid={!!errors.role} />
          </FormField>
          <FormField label={t('education.institution')} required error={errors.company}>
            <Input value={value.company || ''} onChange={(e) => setField('company', e.target.value)} invalid={!!errors.company} />
          </FormField>
          <FormField label={t('education.location')}>
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
          <FormField label={t('education.description')} className="sm:col-span-2">
            <Textarea
              value={value.description || ''}
              placeholder={t('education.description.placeholder')}
              onChange={(e) => setField('description', e.target.value)}
            />
          </FormField>
        </>
      )}
    />
  );
};
