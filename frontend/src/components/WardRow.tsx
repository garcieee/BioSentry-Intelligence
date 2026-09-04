import { Link } from "react-router-dom";
import type { ScoreRow } from "../types";
import { MeasurementDisplay } from "./MeasurementDisplay";
import { Sparkline } from "./Sparkline";
import styles from "./WardRow.module.css";

const TREND_CHAR: Record<string, string> = {
  rising: "\u2191",
  falling: "\u2193",
  stable: "\u2192",
  insufficient: "--",
};

interface Props {
  row: ScoreRow;
}

export function WardRow({ row }: Props) {
  return (
    <Link to={`/patient/${row.id}`} className={styles.link}>
      <div className={styles.row}>
        {/* Rank + score */}
        <div className={styles.rankCol}>
          <span className={styles.rank}>{row.rank}</span>
          <div className={styles.scoreBlock}>
            <span className={styles.score}>{row.score}</span>
            <span className={styles.trend}>{TREND_CHAR[row.trend]}</span>
          </div>
        </div>

        {/* Patient info */}
        <div className={styles.infoCol}>
          <div className={styles.nameRow}>
            <span className={styles.signalDot} data-quality={row.signal_quality > 90 ? "good" : "degraded"} />
            <span className={styles.name}>{row.name}</span>
            <span className={styles.detail}>
              {row.age ?? "--"}{row.sex ? ` ${row.sex}` : ""} &middot; Bed {row.bed}
            </span>
            <span className={styles.updateTag}>{row.last_update_s}s ago</span>
          </div>
          <div className={styles.context}>{row.admitting_context}</div>
          {row.tier_b && (
            <div className={styles.tierBRow}>
              {row.tier_b.arrhythmia_burden !== null && row.tier_b.arrhythmia_burden > 0.05 && (
                <span className={styles.axisBadge}>AF {Math.round(row.tier_b.arrhythmia_burden * 100)}%</span>
              )}
              {row.tier_b.respiratory_trajectory && row.tier_b.respiratory_trajectory !== "stable" && (
                <span className={styles.axisBadge}>Resp {row.tier_b.respiratory_trajectory}</span>
              )}
              {row.tier_b.perfusion_index !== null && row.tier_b.perfusion_index < 0.5 && (
                <span className={styles.axisBadge}>Perfusion {row.tier_b.perfusion_index.toFixed(1)}</span>
              )}
              {row.tier_b.substrate_risk && row.tier_b.substrate_risk !== "normal" && (
                <span className={styles.axisBadge}>{row.tier_b.substrate_risk}</span>
              )}
            </div>
          )}
        </div>

        {/* Sparklines */}
        <div className={styles.sparkCol}>
          <div className={styles.sparkRow}>
            <span className={styles.sparkLabel}>HR</span>
            <Sparkline data={row.vital_trends.heart_rate} width={72} height={20} fill />
            <span className={styles.sparkVal}>
              <MeasurementDisplay measurement={row.vitals.heart_rate} />
            </span>
          </div>
          <div className={styles.sparkRow}>
            <span className={styles.sparkLabel}>RR</span>
            <Sparkline data={row.vital_trends.respiratory_rate} width={72} height={20} fill />
            <span className={styles.sparkVal}>
              <MeasurementDisplay measurement={row.vitals.respiratory_rate} />
            </span>
          </div>
          <div className={styles.sparkRow}>
            <span className={styles.sparkLabel}>SpO2</span>
            <Sparkline data={row.vital_trends.spo2} width={72} height={20} fill />
            <span className={styles.sparkVal}>
              <MeasurementDisplay measurement={row.vitals.spo2} format={(v) => `${v}%`} />
            </span>
          </div>
        </div>

        {/* Nurse-entered + meta */}
        <div className={styles.metaCol}>
          <div className={styles.nursePair}>
            <span className={styles.nurseLabel}>BP</span>
            <MeasurementDisplay measurement={row.vitals.blood_pressure} />
          </div>
          <div className={styles.nursePair}>
            <span className={styles.nurseLabel}>AVPU</span>
            <MeasurementDisplay measurement={row.vitals.consciousness} />
          </div>
          <div className={styles.labLine}>
            {row.labs.freshness_hours !== null
              ? `Labs ${row.labs.freshness_hours}h`
              : "No labs"}
          </div>
          <span className={styles.tierTag}>Tier {row.sort_tier}</span>
        </div>
      </div>
    </Link>
  );
}
