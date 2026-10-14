import { useState } from "react";
import type { AbstainedRow as AbstainedRowType, VitalsRecorded } from "../types";
import styles from "./AbstainedRow.module.css";
import { VitalsEntry } from "./VitalsEntry";

interface Props {
  row: AbstainedRowType;
  /** HTTP mode only: the fixture provider cannot re-rank, so it offers no entry (D4). */
  canRecord?: boolean;
  /** Who is recording (shown in the echo of what will be stored). */
  clinicianId?: string;
  onRecorded?: (row: AbstainedRowType, recorded: VitalsRecorded) => void;
}

export function AbstainedRow({ row, canRecord = false, clinicianId = "", onRecorded }: Props) {
  const [entering, setEntering] = useState(false);
  return (
    <div className={styles.row}>
      <div className={styles.tagCol}>
        <span className={styles.tag}>NOT RANKED</span>
      </div>
      <div className={styles.infoCol}>
        <div className={styles.nameRow}>
          <span className={styles.name}>{row.name}</span>
          <span className={styles.detail}>
            {row.age ?? "--"}{row.sex ? ` ${row.sex}` : ""} &middot; Bed {row.bed}
          </span>
        </div>
        <div className={styles.context}>{row.admitting_context}</div>
      </div>
      <div className={styles.reasonCol}>
        <div className={styles.reason}>{row.reason}</div>
        <div className={styles.instruction}>{row.instruction}</div>
        {canRecord && (
          <button
            type="button"
            className={styles.action}
            aria-expanded={entering}
            onClick={() => setEntering((open) => !open)}
          >
            {entering ? "Close" : "Record vitals"}
          </button>
        )}
      </div>
      {canRecord && entering && (
        <div className={styles.entry}>
          <VitalsEntry
            patientId={row.id}
            patientName={row.name}
            clinicianId={clinicianId}
            onRecorded={(recorded) => onRecorded?.(row, recorded)}
            onClose={() => setEntering(false)}
          />
        </div>
      )}
    </div>
  );
}
