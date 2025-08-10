import React from 'react';
import type { JobRecord } from '../App';
import { useI18n } from '../i18n';

interface Props { jobs: JobRecord[]; onRemove: (index: number) => void }

export const JobsTable: React.FC<Props> = ({ jobs, onRemove }) => {
  const { t } = useI18n();
  if (!jobs.length) return <p>{t('jobs.none')}</p>;
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: '1rem' }}>
      <thead>
        <tr>
          <th style={th}>{t('jobs.title')}</th>
          <th style={th}>{t('jobs.company')}</th>
          <th style={th}>{t('jobs.start')}</th>
          <th style={th}>{t('jobs.end')}</th>
          <th style={th}>{t('jobs.description')}</th>
          <th style={th}>{t('jobs.actions')}</th>
        </tr>
      </thead>
      <tbody>
        {jobs.map((j, i) => (
          <tr key={i}>
            <td style={td}>{j.title}</td>
            <td style={td}>{j.company}</td>
            <td style={td}>{j.startDate}</td>
            <td style={td}>{j.endDate || t('present')}</td>
            <td style={td}>{j.description.slice(0, 80)}{j.description.length > 80 ? '…' : ''}</td>
            <td style={td}><button onClick={() => onRemove(i)}>{t('jobs.remove')}</button></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
};

const th: React.CSSProperties = { borderBottom: '1px solid #555', textAlign: 'left', padding: 4 };
const td: React.CSSProperties = { borderBottom: '1px solid #333', padding: 4, verticalAlign: 'top' };
