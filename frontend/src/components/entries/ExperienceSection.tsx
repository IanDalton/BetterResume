import React from 'react';
import { ResumeEntry } from '../../types';
import { FormField, Input, Textarea, Select } from '../ui';
import { EntrySectionCard } from './EntrySectionCard';
import { MonthYearInput } from './MonthYearInput';
import { experienceEntrySchema } from './validation';
import { useI18n } from '../../i18n';

interface Props {
  entries: ResumeEntry[];
  onAdd: (e: ResumeEntry) => void;
  onUpdate: (i: number, e: ResumeEntry) => void;
  onRemove: (i: number) => void;
}

const EXPERIENCE_SECTION_TYPES = ['job', 'contract', 'part-time', 'project', 'non-profit'] as const;

export const ExperienceSection: React.FC<Props> = ({ entries, onAdd, onUpdate, onRemove }) => {
  const { t } = useI18n();
  const hasAny = entries.some((e) => (EXPERIENCE_SECTION_TYPES as readonly string[]).includes(e.type));
  const typeOptions = EXPERIENCE_SECTION_TYPES.map((v) => ({ value: v, label: t(`type.${v}`) }));

  return (
    <EntrySectionCard
      title={t('section.experience.title')}
      hint={t('section.experience.hint')}
      addLabel={t('experience.add')}
      emptyLabel={t('entries.none')}
      types={[...EXPERIENCE_SECTION_TYPES]}
      defaultType="job"
      entries={entries}
      onAdd={onAdd}
      onUpdate={onUpdate}
      onRemove={onRemove}
      schema={experienceEntrySchema}
      isComplete={hasAny}
      renderFields={({ value, setField, errors }) => (
        <>
          <FormField label={t('field.type')}>
            <Select options={typeOptions} value={value.type} onValueChange={(v) => setField('type', v)} />
          </FormField>
          <FormField label={t('experience.role.placeholder')} required error={errors.role}>
            <Input value={value.role} onChange={(e) => setField('role', e.target.value)} invalid={!!errors.role} />
          </FormField>
          <FormField label={t('experience.company.placeholder')} required error={errors.company}>
            <Input value={value.company || ''} onChange={(e) => setField('company', e.target.value)} invalid={!!errors.company} />
          </FormField>
          <FormField label={t('experience.location.placeholder')}>
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
          <FormField label={t('experience.description.placeholder')} className="sm:col-span-2">
            <Textarea value={value.description || ''} onChange={(e) => setField('description', e.target.value)} />
          </FormField>
        </>
      )}
    />
  );
};
