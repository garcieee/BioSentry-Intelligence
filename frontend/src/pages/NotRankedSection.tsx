import { canRecordVitals } from "../api";
import { AbstainedRow } from "../components/AbstainedRow";
import type { AbstainedRow as AbstainedRowType, VitalsRecorded } from "../types";
import styles from "./Ward.module.css";

interface Props {
  readonly rows: readonly AbstainedRowType[];
  readonly clinicianId: string;
  readonly onRecorded: (row: AbstainedRowType, recorded: VitalsRecorded) => void;
}

/**
 * The NOT RANKED list. Whether a row offers vitals entry is decided here, once, from the
 * build's capability: only the API can re-rank, so the fixture build offers none (D4).
 */
export function NotRankedSection({ rows, clinicianId, onRecorded }: Props) {
  if (rows.length === 0) return null;
  return (
    <>
      <div className={styles.sectionHeader}>
        <p className={styles.eyebrow}>Not ranked ({rows.length})</p>
        <p className={styles.sortInfo}>Action required to enable scoring</p>
      </div>
      <div className={styles.rowList}>
        {rows.map((row) => (
          <AbstainedRow
            key={row.id}
            row={row}
            canRecord={canRecordVitals}
            clinicianId={clinicianId}
            onRecorded={onRecorded}
          />
        ))}
      </div>
    </>
  );
}
