import type { ReactElement } from "react";
import type { Vitals } from "../types";
import styles from "../pages/PatientDetail.module.css";
import { formatBloodPressure, formatOxygen, formatSpo2Scale } from "./format";
import { MeasurementDisplay, type MeasurementProps } from "./MeasurementDisplay";

type Primitive = string | number | boolean;
type RowProps<T> = MeasurementProps<T> & { label: string };

function Row<T>({
  label,
  measurement,
  unit,
  format,
}: RowProps<T> & { format?: (value: T) => string }): ReactElement {
  return (
    <div className={styles.vitalRow}>
      <span className={styles.vitalLabel}>{label}</span>
      <span className={styles.vitalValue}>
        {/* The overloads on VitalRow enforce a format() for structured values. */}
        <MeasurementDisplay
          measurement={measurement}
          unit={unit}
          format={format as (value: T) => string}
        />
      </span>
    </div>
  );
}

export const VitalRow = Row as {
  <T extends Primitive>(props: RowProps<T> & { format?: (value: T) => string }): ReactElement;
  <T>(props: RowProps<T> & { format: (value: T) => string }): ReactElement;
};

/** The CURRENT VITALS block of the patient detail page. */
export function CurrentVitals({ vitals }: { vitals: Vitals }): ReactElement {
  return (
    <>
      <VitalRow label="Heart rate" measurement={vitals.heart_rate} unit="bpm" />
      <VitalRow label="Respiratory rate" measurement={vitals.respiratory_rate} unit="/min" />
      <VitalRow label="SpO2" measurement={vitals.spo2} unit="%" />
      <VitalRow label="Temperature" measurement={vitals.temperature} unit={"°C"} />
      <VitalRow
        label="Blood pressure"
        measurement={vitals.blood_pressure}
        format={formatBloodPressure}
      />
      <VitalRow label="Consciousness" measurement={vitals.consciousness} />
      <VitalRow label="Oxygen" measurement={vitals.supplemental_o2} format={formatOxygen} />
      <VitalRow label="SpO2 scale" measurement={vitals.spo2_scale} format={formatSpo2Scale} />
    </>
  );
}
