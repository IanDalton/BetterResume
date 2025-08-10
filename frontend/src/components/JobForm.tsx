import React, { useState } from 'react';
import type { JobRecord } from '../App';
import { useI18n } from '../i18n';

interface Props { onAdd: (job: JobRecord) => void }

const empty: JobRecord = { title: '', company: '', startDate: '', endDate: '', description: '' };

export const JobForm: React.FC<Props> = ({ onAdd }) => {
  const [form, setForm] = useState<JobRecord>(empty);
  const { t } = useI18n();

  const update = (k: keyof JobRecord, v: string) => setForm(prev => ({ ...prev, [k]: v }));

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.title || !form.company) return;
    onAdd(form);
    setForm(empty);
  };

  return (
    <form onSubmit={submit} style={{ display: 'grid', gap: '0.5rem', maxWidth: 600 }}>
      <input required placeholder={t('jobs.title')} value={form.title} onChange={e => update('title', e.target.value)} />
      <input required placeholder={t('jobs.company')} value={form.company} onChange={e => update('company', e.target.value)} />
      <div style={{ display: 'flex', gap: '0.5rem' }}>
        <input required type='month' placeholder={t('jobs.start')} value={form.startDate} onChange={e => update('startDate', e.target.value)} />
        <input type='month' placeholder={t('jobs.end')} value={form.endDate} onChange={e => update('endDate', e.target.value)} />
      </div>
      <textarea placeholder={t('jobs.description')} value={form.description} onChange={e => update('description', e.target.value)} />
      <button type='submit'>{t('button.addEntry')}</button>
    </form>
  );
};
