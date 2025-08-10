import React from 'react';
import type { JobRecord } from '../App';

interface Props { jobs: JobRecord[]; onRemove: (index: number) => void }

export const JobsTable: React.FC<Props> = ({ jobs, onRemove }) => {
  if (!jobs.length) return <p>No jobs added yet.</p>;
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: '1rem' }}>
      <thead>
        <tr>
          <th style={th}>Title</th>
          <th style={th}>Company</th>
          <th style={th}>Start</th>
          <th style={th}>End</th>
          <th style={th}>Description</th>
          <th style={th}>Actions</th>
        </tr>
      </thead>
      <tbody>
        {jobs.map((j, i) => (
          <tr key={i}>
            <td style={td}>{j.title}</td>
            <td style={td}>{j.company}</td>
            <td style={td}>{j.startDate}</td>
            <td style={td}>{j.endDate || 'Present'}</td>
            <td style={td}>{j.description.slice(0, 80)}{j.description.length > 80 ? '…' : ''}</td>
            <td style={td}><button onClick={() => onRemove(i)}>Remove</button></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
};

const th: React.CSSProperties = { borderBottom: '1px solid #555', textAlign: 'left', padding: 4 };
const td: React.CSSProperties = { borderBottom: '1px solid #333', padding: 4, verticalAlign: 'top' };
