import type { AbstainedRow as AbstainedRowType } from "../types";
import styles from "./AbstainedRow.module.css";

interface Props {
  row: AbstainedRowType;
}

export function AbstainedRow({ row }: Props) {
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
      </div>
    </div>
  );
}
