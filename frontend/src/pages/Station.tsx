import { useEffect, useRef, useState, type FormEvent } from "react";
import type { Session, AdmitPatientInput, LabExtractionResult, PatientExtractionResult } from "../types";
import { admitPatient, enterLabResults, extractLabsFromFile, extractPatientFromFile, listAllPatients } from "../api";
import { SessionMenu } from "../components/SessionMenu";
import styles from "./Station.module.css";

interface Props {
  session: Session;
  onSignOut: () => void;
}

const PHYSICIANS = [
  "Dr. Santos",
  "Dr. Reyes",
  "Dr. Aquino",
  "Dr. Villanueva",
];

type Section = "admit" | "labs" | "upload";

export function Station({ session, onSignOut }: Props) {
  const [section, setSection] = useState<Section>("admit");

  return (
    <div className={styles.page}>
      <div className={styles.statusBar}>
        <div className={styles.statusInner}>
          <div className={styles.statusLeft}>
            <span className={styles.statusLabel}>BioSentry</span>
            <span className={styles.statusValue}>Station &middot; Ward {session.ward}</span>
          </div>
          <div className={styles.statusRight}>
            <SessionMenu session={session} onSignOut={onSignOut} />
          </div>
        </div>
      </div>

      <div className={styles.tabBar}>
        <button
          type="button"
          className={`${styles.tab} ${section === "admit" ? styles.tabActive : ""}`}
          onClick={() => setSection("admit")}
        >
          Admit patient
        </button>
        <button
          type="button"
          className={`${styles.tab} ${section === "labs" ? styles.tabActive : ""}`}
          onClick={() => setSection("labs")}
        >
          Enter lab results
        </button>
        <button
          type="button"
          className={`${styles.tab} ${section === "upload" ? styles.tabActive : ""}`}
          onClick={() => setSection("upload")}
        >
          Upload
        </button>
      </div>

      <main className={styles.container}>
        {section === "admit" && <AdmitForm />}
        {section === "labs" && <LabForm />}
        {section === "upload" && <UploadForm />}
      </main>
    </div>
  );
}

// --- Admit Patient Form ---

function AdmitForm() {
  const [lastName, setLastName] = useState("");
  const [firstName, setFirstName] = useState("");
  const [middleName, setMiddleName] = useState("");
  const [dob, setDob] = useState("");
  const [age, setAge] = useState("");
  const [sex, setSex] = useState<"M" | "F" | "">("");
  const [contactNumber, setContactNumber] = useState("");
  const [bed, setBed] = useState("");
  const [route, setRoute] = useState<"er_triage" | "direct_admission" | "transfer">("er_triage");
  const [chiefComplaint, setChiefComplaint] = useState("");
  const [context, setContext] = useState("");
  const [allergies, setAllergies] = useState("");
  const [physician, setPhysician] = useState(PHYSICIANS[0]);
  const [weightKg, setWeightKg] = useState("");
  const [heightCm, setHeightCm] = useState("");
  const [bp, setBp] = useState("");
  const [avpu, setAvpu] = useState("");
  const [result, setResult] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const canSubmit = lastName.trim() && firstName.trim() && dob && age && sex && bed.trim() && chiefComplaint.trim() && context.trim();

  const handleDobChange = (value: string) => {
    setDob(value);
    if (value) {
      const birth = new Date(value);
      const today = new Date();
      let years = today.getFullYear() - birth.getFullYear();
      const m = today.getMonth() - birth.getMonth();
      if (m < 0 || (m === 0 && today.getDate() < birth.getDate())) years--;
      setAge(String(Math.max(0, years)));
    }
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit || submitting) return;
    setSubmitting(true);

    const input: AdmitPatientInput = {
      lastName: lastName.trim(),
      firstName: firstName.trim(),
      ...(middleName.trim() ? { middleName: middleName.trim() } : {}),
      dateOfBirth: dob,
      age: parseInt(age, 10),
      sex: sex as "M" | "F",
      ...(contactNumber.trim() ? { contactNumber: contactNumber.trim() } : {}),
      bed: bed.trim(),
      admissionRoute: route,
      chiefComplaint: chiefComplaint.trim(),
      admittingContext: context.trim(),
      attendingPhysician: physician,
      ...(allergies.trim() ? { allergies: allergies.trim() } : {}),
      ...(weightKg ? { weightKg: parseFloat(weightKg) } : {}),
      ...(heightCm ? { heightCm: parseFloat(heightCm) } : {}),
      ...(bp.trim() ? { initialBp: bp.trim() } : {}),
      ...(avpu ? { initialAvpu: avpu as "A" | "V" | "P" | "U" } : {}),
    };

    const row = await admitPatient(input);
    setResult(`Admitted ${row.name} as ${row.id} -- Bed ${row.bed}. Status: NOT RANKED (patch not yet applied).`);
    setLastName(""); setFirstName(""); setMiddleName("");
    setDob(""); setAge(""); setSex(""); setContactNumber("");
    setBed(""); setChiefComplaint(""); setContext(""); setAllergies("");
    setWeightKg(""); setHeightCm(""); setBp(""); setAvpu("");
    setSubmitting(false);
  };

  return (
    <form className={styles.form} onSubmit={handleSubmit}>
      <p className={styles.formTitle}>Admit patient</p>
      <p className={styles.formSub}>
        New patients are added as NOT RANKED until a chest patch is applied and signal is verified.
      </p>

      {result && (
        <div className={styles.successBanner}>
          {result}
          <button type="button" className={styles.dismissBtn} onClick={() => setResult(null)}>&times;</button>
        </div>
      )}

      <p className={styles.sectionDivider}>Patient identity</p>

      <div className={styles.fieldRow}>
        <div className={styles.field}>
          <label className={styles.label}>Last name</label>
          <input className={styles.input} value={lastName} onChange={(e) => setLastName(e.target.value)} required />
        </div>
        <div className={styles.field}>
          <label className={styles.label}>First name</label>
          <input className={styles.input} value={firstName} onChange={(e) => setFirstName(e.target.value)} required />
        </div>
        <div className={styles.field}>
          <label className={styles.label}>Middle name</label>
          <input className={styles.input} value={middleName} onChange={(e) => setMiddleName(e.target.value)} />
        </div>
      </div>

      <div className={styles.fieldRow}>
        <div className={styles.field}>
          <label className={styles.label}>Date of birth</label>
          <input className={styles.input} type="date" value={dob} onChange={(e) => handleDobChange(e.target.value)} required />
        </div>
        <div className={styles.field}>
          <label className={styles.label}>Age</label>
          <input className={styles.input} type="number" min={0} max={150} value={age} onChange={(e) => setAge(e.target.value)} required />
        </div>
        <div className={styles.field}>
          <label className={styles.label}>Sex</label>
          <select className={styles.select} value={sex} onChange={(e) => setSex(e.target.value as "M" | "F" | "")} required>
            <option value="">--</option>
            <option value="M">M</option>
            <option value="F">F</option>
          </select>
        </div>
      </div>

      <div className={styles.fieldRow}>
        <div className={styles.field}>
          <label className={styles.label}>Contact number</label>
          <input className={styles.input} type="tel" placeholder="09XX XXX XXXX" value={contactNumber} onChange={(e) => setContactNumber(e.target.value)} />
        </div>
        <div className={styles.field}>
          <label className={styles.label}>Bed</label>
          <input className={styles.input} placeholder="e.g. MW-4A" value={bed} onChange={(e) => setBed(e.target.value)} required />
        </div>
      </div>

      <p className={styles.sectionDivider}>Admission details</p>

      <div className={styles.fieldRow}>
        <div className={styles.field}>
          <label className={styles.label}>Admission route</label>
          <select className={styles.select} value={route} onChange={(e) => setRoute(e.target.value as "er_triage" | "direct_admission" | "transfer")}>
            <option value="er_triage">ER Triage</option>
            <option value="direct_admission">Direct Ward Admission</option>
            <option value="transfer">Transfer from another facility</option>
          </select>
        </div>
        <div className={styles.field}>
          <label className={styles.label}>Attending physician</label>
          <select className={styles.select} value={physician} onChange={(e) => setPhysician(e.target.value)}>
            {PHYSICIANS.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
        </div>
      </div>

      <div className={styles.field}>
        <label className={styles.label}>Chief complaint</label>
        <input className={styles.input} placeholder="e.g. Chest pain, onset 2 hours ago" value={chiefComplaint} onChange={(e) => setChiefComplaint(e.target.value)} required />
      </div>

      <div className={styles.field}>
        <label className={styles.label}>Admitting diagnosis / context</label>
        <textarea className={styles.textarea} rows={3} value={context} onChange={(e) => setContext(e.target.value)} required />
      </div>

      <div className={styles.field}>
        <label className={styles.label}>Allergies</label>
        <input className={styles.input} placeholder="NKDA or list allergies" value={allergies} onChange={(e) => setAllergies(e.target.value)} />
      </div>

      <p className={styles.sectionDivider}>Initial assessment (nurse-entered)</p>

      <div className={styles.fieldRow}>
        <div className={styles.field}>
          <label className={styles.label}>Weight (kg)</label>
          <input className={styles.input} type="number" step="0.1" min={0} value={weightKg} onChange={(e) => setWeightKg(e.target.value)} />
        </div>
        <div className={styles.field}>
          <label className={styles.label}>Height (cm)</label>
          <input className={styles.input} type="number" step="0.1" min={0} value={heightCm} onChange={(e) => setHeightCm(e.target.value)} />
        </div>
      </div>

      <div className={styles.fieldRow}>
        <div className={styles.field}>
          <label className={styles.label}>Blood pressure (sys/dia)</label>
          <input className={styles.input} placeholder="e.g. 120/80" value={bp} onChange={(e) => setBp(e.target.value)} />
        </div>
        <div className={styles.field}>
          <label className={styles.label}>Consciousness (AVPU)</label>
          <select className={styles.select} value={avpu} onChange={(e) => setAvpu(e.target.value)}>
            <option value="">--</option>
            <option value="A">Alert</option>
            <option value="V">Verbal</option>
            <option value="P">Pain</option>
            <option value="U">Unresponsive</option>
          </select>
        </div>
      </div>

      <button type="submit" className={styles.submitBtn} disabled={!canSubmit || submitting}>
        Admit patient
      </button>
    </form>
  );
}

// --- Enter Lab Results Form ---

// Lab field config: key, label, unit
const LAB_FIELDS: Array<{ key: string; label: string; unit: string; section: string }> = [
  { key: "troponin", label: "Troponin", unit: "ng/mL", section: "Cardiac biomarkers" },
  { key: "ck_mb", label: "CK-MB", unit: "U/L", section: "Cardiac biomarkers" },
  { key: "bnp", label: "BNP", unit: "pg/mL", section: "Cardiac biomarkers" },
  { key: "nt_probnp", label: "NT-proBNP", unit: "pg/mL", section: "Cardiac biomarkers" },
  { key: "sodium", label: "Sodium", unit: "mEq/L", section: "Electrolytes" },
  { key: "potassium", label: "Potassium", unit: "mEq/L", section: "Electrolytes" },
  { key: "magnesium", label: "Magnesium", unit: "mg/dL", section: "Electrolytes" },
  { key: "calcium", label: "Calcium", unit: "mg/dL", section: "Electrolytes" },
  { key: "creatinine", label: "Creatinine", unit: "mg/dL", section: "Renal" },
  { key: "bun", label: "BUN", unit: "mg/dL", section: "Renal" },
  { key: "hemoglobin", label: "Hemoglobin", unit: "g/L", section: "Hematology" },
  { key: "wbc", label: "WBC", unit: "x10^9/L", section: "Hematology" },
  { key: "platelet_count", label: "Platelets", unit: "/mm^3", section: "Hematology" },
  { key: "inr", label: "INR", unit: "", section: "Coagulation" },
  { key: "sgpt", label: "SGPT", unit: "U/L", section: "Liver" },
  { key: "sgot", label: "SGOT", unit: "U/L", section: "Liver" },
  { key: "blood_glucose", label: "Blood glucose", unit: "mg/dL", section: "Metabolic" },
];

function LabForm() {
  const [patients, setPatients] = useState<Array<{ id: string; name: string; bed: string; ranked: boolean }>>([]);
  const [selectedId, setSelectedId] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const [result, setResult] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    listAllPatients().then(setPatients);
  }, []);

  const hasAnyLab = LAB_FIELDS.some((f) => values[f.key]?.trim());
  const selectedPatient = patients.find((p) => p.id === selectedId);
  const canSubmit = selectedId && hasAnyLab && selectedPatient?.ranked;

  const setField = (key: string, val: string) =>
    setValues((prev) => ({ ...prev, [key]: val }));

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit || submitting) return;
    setSubmitting(true);

    const labs: Record<string, number> = {};
    for (const f of LAB_FIELDS) {
      const v = values[f.key];
      if (v?.trim()) {
        const n = parseFloat(v);
        if (!isNaN(n)) labs[f.key] = n;
      }
    }

    await enterLabResults(selectedId, labs);
    const names = Object.keys(labs).map((k) => LAB_FIELDS.find((f) => f.key === k)?.label ?? k).join(", ");
    setResult(`Lab results recorded for ${selectedPatient?.name} (${selectedId}): ${names}.`);
    setValues({});
    setSubmitting(false);
  };

  return (
    <form className={styles.form} onSubmit={handleSubmit}>
      <p className={styles.formTitle}>Enter lab results</p>
      <p className={styles.formSub}>
        Select a ranked patient and enter one or more lab values. Lab entry for non-ranked patients will be available once they have an active patch.
      </p>

      {result && (
        <div className={styles.successBanner}>
          {result}
          <button type="button" className={styles.dismissBtn} onClick={() => setResult(null)}>&times;</button>
        </div>
      )}

      <div className={styles.field}>
        <label className={styles.label}>Patient</label>
        <select className={styles.select} value={selectedId} onChange={(e) => setSelectedId(e.target.value)} required>
          <option value="">Select patient...</option>
          {patients.filter((p) => p.ranked).map((p) => (
            <option key={p.id} value={p.id}>
              {p.name} -- Bed {p.bed} ({p.id})
            </option>
          ))}
          {patients.filter((p) => !p.ranked).length > 0 && (
            <optgroup label="Not ranked (lab entry pending patch)">
              {patients.filter((p) => !p.ranked).map((p) => (
                <option key={p.id} value={p.id} disabled>
                  {p.name} -- Bed {p.bed} ({p.id})
                </option>
              ))}
            </optgroup>
          )}
        </select>
      </div>

      {(() => {
        const sections: string[] = [];
        for (const f of LAB_FIELDS) {
          if (!sections.includes(f.section)) sections.push(f.section);
        }
        return sections.map((sec) => (
          <div key={sec}>
            <p className={styles.sectionDivider}>{sec}</p>
            <div className={styles.fieldRow}>
              {LAB_FIELDS.filter((f) => f.section === sec).map((f) => (
                <div key={f.key} className={styles.field}>
                  <label className={styles.label}>{f.label}{f.unit ? ` (${f.unit})` : ""}</label>
                  <input
                    className={styles.input}
                    type="number"
                    step="any"
                    min={0}
                    value={values[f.key] ?? ""}
                    onChange={(e) => setField(f.key, e.target.value)}
                  />
                </div>
              ))}
            </div>
          </div>
        ));
      })()}

      <button type="submit" className={styles.submitBtn} disabled={!canSubmit || submitting}>
        Record lab results
      </button>
    </form>
  );
}

// --- Upload (document extraction for labs or patient records) ---

type UploadType = "lab" | "patient";
type UploadStep = "select" | "review" | "done";

const LAB_LABELS: Record<string, string> = Object.fromEntries(
  LAB_FIELDS.map((f) => [f.key, f.unit ? `${f.label} (${f.unit})` : f.label])
);

const PATIENT_LABELS: Record<string, string> = {
  lastName: "Last name",
  firstName: "First name",
  middleName: "Middle name",
  dateOfBirth: "Date of birth",
  age: "Age",
  sex: "Sex",
  contactNumber: "Contact number",
  bed: "Bed",
  admissionRoute: "Admission route",
  chiefComplaint: "Chief complaint",
  admittingContext: "Admitting diagnosis / context",
  attendingPhysician: "Attending physician",
  allergies: "Allergies",
};

function UploadForm() {
  const [uploadType, setUploadType] = useState<UploadType>("lab");
  const [patients, setPatients] = useState<Array<{ id: string; name: string; bed: string; ranked: boolean }>>([]);
  const [selectedId, setSelectedId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [step, setStep] = useState<UploadStep>("select");
  const [labExtraction, setLabExtraction] = useState<LabExtractionResult | null>(null);
  const [patientExtraction, setPatientExtraction] = useState<PatientExtractionResult | null>(null);
  const [editedValues, setEditedValues] = useState<Record<string, string>>({});
  const [extracting, setExtracting] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    listAllPatients().then(setPatients);
  }, []);

  const selectedPatient = patients.find((p) => p.id === selectedId);
  const canExtractLab = uploadType === "lab" && selectedId && file && selectedPatient?.ranked;
  const canExtractPatient = uploadType === "patient" && file;
  const canExtract = canExtractLab || canExtractPatient;

  const handleExtract = async () => {
    if (!canExtract || !file) return;
    setExtracting(true);

    if (uploadType === "lab") {
      const res = await extractLabsFromFile(file);
      setLabExtraction(res);
      const initial: Record<string, string> = {};
      for (const [key, val] of Object.entries(res.values)) {
        if (val !== undefined) initial[key] = String(val);
      }
      setEditedValues(initial);
    } else {
      const res = await extractPatientFromFile(file);
      setPatientExtraction(res);
      const initial: Record<string, string> = {};
      for (const [key, val] of Object.entries(res.values)) {
        if (val !== undefined) initial[key] = String(val);
      }
      setEditedValues(initial);
    }

    setExtracting(false);
    setStep("review");
  };

  const handleConfirmLab = async () => {
    if (!selectedId || submitting) return;
    setSubmitting(true);

    const labs: Record<string, number> = {};
    for (const [key, val] of Object.entries(editedValues)) {
      const n = parseFloat(val);
      if (!isNaN(n) && val.trim()) labs[key] = n;
    }

    await enterLabResults(selectedId, labs);
    const names = Object.keys(labs).join(", ");
    setResult(`Lab results recorded for ${selectedPatient?.name} (${selectedId}): ${names}.`);
    setStep("done");
    setSubmitting(false);
  };

  const handleConfirmPatient = async () => {
    if (submitting) return;
    setSubmitting(true);

    const v = editedValues;
    const input: AdmitPatientInput = {
      lastName: v.lastName?.trim() || "Unknown",
      firstName: v.firstName?.trim() || "Unknown",
      ...(v.middleName?.trim() ? { middleName: v.middleName.trim() } : {}),
      dateOfBirth: v.dateOfBirth?.trim() || "1970-01-01",
      age: parseInt(v.age, 10) || 0,
      sex: (v.sex === "M" || v.sex === "F") ? v.sex : "M",
      ...(v.contactNumber?.trim() ? { contactNumber: v.contactNumber.trim() } : {}),
      bed: v.bed?.trim() || "TBD",
      admissionRoute: v.admissionRoute === "direct_admission" ? "direct_admission"
        : v.admissionRoute === "transfer" ? "transfer" : "er_triage",
      chiefComplaint: v.chiefComplaint?.trim() || "See uploaded document",
      admittingContext: v.admittingContext?.trim() || "Extracted from uploaded document",
      attendingPhysician: v.attendingPhysician?.trim() || PHYSICIANS[0],
      ...(v.allergies?.trim() ? { allergies: v.allergies.trim() } : {}),
    };

    const row = await admitPatient(input);
    setResult(`Admitted ${row.name} as ${row.id} -- Bed ${row.bed}. Status: NOT RANKED (patch not yet applied).`);
    setStep("done");
    setSubmitting(false);
  };

  const handleReset = () => {
    setFile(null);
    setLabExtraction(null);
    setPatientExtraction(null);
    setEditedValues({});
    setStep("select");
    setResult(null);
    if (fileRef.current) fileRef.current.value = "";
  };

  return (
    <div className={styles.form}>
      <p className={styles.formTitle}>Upload document</p>
      <p className={styles.formSub}>
        Upload a lab result or patient record. Values are read from the document for you to review and confirm before saving.
      </p>

      <div className={styles.syntheticBanner}>
        Document reading is simulated in this pilot build. Values shown are sample data, not from the uploaded file.
      </div>

      {result && (
        <div className={styles.successBanner}>
          {result}
          <button type="button" className={styles.dismissBtn} onClick={handleReset}>&times;</button>
        </div>
      )}

      {step === "select" && (
        <>
          <div className={styles.field}>
            <label className={styles.label}>Document type</label>
            <select
              className={styles.select}
              value={uploadType}
              onChange={(e) => { setUploadType(e.target.value as UploadType); setSelectedId(""); }}
            >
              <option value="lab">Lab results</option>
              <option value="patient">Patient record (admission)</option>
            </select>
          </div>

          {uploadType === "lab" && (
            <div className={styles.field}>
              <label className={styles.label}>Patient</label>
              <select className={styles.select} value={selectedId} onChange={(e) => setSelectedId(e.target.value)}>
                <option value="">Select patient...</option>
                {patients.filter((p) => p.ranked).map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} -- Bed {p.bed} ({p.id})
                  </option>
                ))}
              </select>
            </div>
          )}

          <div className={styles.field}>
            <label className={styles.label}>File</label>
            <input
              ref={fileRef}
              className={styles.input}
              type="file"
              accept=".pdf,.jpg,.jpeg,.png"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </div>

          {file && (
            <div className={styles.filePreview}>
              <span className={styles.fileName}>{file.name}</span>
              <span className={styles.fileSize}>{(file.size / 1024).toFixed(1)} KB</span>
            </div>
          )}

          <button
            type="button"
            className={styles.submitBtn}
            disabled={!canExtract || extracting}
            onClick={handleExtract}
          >
            {extracting ? "Reading document..." : "Read document"}
          </button>
        </>
      )}

      {step === "review" && uploadType === "lab" && labExtraction && (
        <>
          <p className={styles.sectionDivider}>Values read from document -- review and correct</p>

          <div className={styles.extractionGrid}>
            {Object.entries(labExtraction.values).map(([key, val]) => {
              if (val === undefined) return null;
              const conf = labExtraction.confidence[key];
              return (
                <div key={key} className={styles.extractionRow}>
                  <span className={styles.extractionLabel}>{LAB_LABELS[key] ?? key}</span>
                  <input
                    className={styles.input}
                    type="number"
                    step="any"
                    value={editedValues[key] ?? ""}
                    onChange={(e) => setEditedValues((prev) => ({ ...prev, [key]: e.target.value }))}
                  />
                  {conf !== undefined && (
                    <span className={styles.confidence}>{Math.round(conf * 100)}%</span>
                  )}
                </div>
              );
            })}
          </div>

          <div className={styles.reviewActions}>
            <button type="button" className={styles.submitBtn} disabled={submitting} onClick={handleConfirmLab}>
              {submitting ? "Saving..." : "Confirm and save"}
            </button>
            <button type="button" className={styles.cancelBtn} onClick={handleReset}>Cancel</button>
          </div>
        </>
      )}

      {step === "review" && uploadType === "patient" && patientExtraction && (
        <>
          <p className={styles.sectionDivider}>Values read from document -- review and correct</p>

          <div className={styles.extractionGrid}>
            {Object.entries(patientExtraction.values).map(([key, val]) => {
              if (val === undefined) return null;
              const conf = patientExtraction.confidence[key];
              return (
                <div key={key} className={styles.extractionRow}>
                  <span className={styles.extractionLabel}>{PATIENT_LABELS[key] ?? key}</span>
                  <input
                    className={styles.input}
                    type="text"
                    value={editedValues[key] ?? ""}
                    onChange={(e) => setEditedValues((prev) => ({ ...prev, [key]: e.target.value }))}
                  />
                  {conf !== undefined && (
                    <span className={styles.confidence}>{Math.round(conf * 100)}%</span>
                  )}
                </div>
              );
            })}
          </div>

          <div className={styles.reviewActions}>
            <button type="button" className={styles.submitBtn} disabled={submitting} onClick={handleConfirmPatient}>
              {submitting ? "Admitting..." : "Confirm and admit"}
            </button>
            <button type="button" className={styles.cancelBtn} onClick={handleReset}>Cancel</button>
          </div>
        </>
      )}

      {step === "done" && (
        <button type="button" className={styles.submitBtn} onClick={handleReset}>
          Upload another
        </button>
      )}
    </div>
  );
}
