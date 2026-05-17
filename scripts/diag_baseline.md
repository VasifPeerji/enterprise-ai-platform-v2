# RAG diagnostic against `test-docs4`
_2026-05-08 00:28:09_

### U1_acet_45kg
**Query:** What is the maximum daily dose of acetaminophen injection for an adult weighing 45 kg?
**Expected:** Acetaminophen.pdf | KWs: [75 mg/kg, 3750 mg]
**User symptom:** False negative ('No relevant knowledge found')

- /analyze: retrieval_count=0 top_score=0.000 2nd=0.000
- citations=0 pages=[] expected_doc_in_top=False
- snippet_lens=[] truncated=[]
- first_snippet[:160]=''
- expected_kw_in_snippets: 75 mg/kg=N, 3750 mg=N
- page_proofs=0 highlight_spans=0 highlight_chars=0 page_text_chars=0
  -> highlight coverage: 0.0%
- section_titles[0:3]: 
- ARTICLE_SECTION_LEAK (Bug E): False

- /answer: status=404 grounded=None err='No relevant knowledge found for query'
- answer[:240]=''

### U2_proair_dose_counter
**Query:** How does the dose counter on the ProAir HFA inhaler work, and when should the inhaler be discarded?
**Expected:** Albuterol.pdf | KWs: [200, 20, RED, discard, expiration]
**User symptom:** Grounded query failed

- /analyze: retrieval_count=6 top_score=1.357 2nd=1.339
- citations=6 pages=[7, 2, 1, 2, 3, 3] expected_doc_in_top=True
- snippet_lens=[71, 41, 55, 60, 55, 73] truncated=[True, True, True, True, True, True]
- first_snippet[:160]='LIMIT the dose of simvastatin in patients on amlodipine to 20 mg daily.'
- expected_kw_in_snippets: 200=Y, 20=Y, RED=Y, discard=N, expiration=N
- page_proofs=6 highlight_spans=6 highlight_chars=355 page_text_chars=8488
  -> highlight coverage: 4.2%
- section_titles[0:3]: DRUG: AMLODIPINE BESYLATE (NORVASC) | SECTION: DRUG INTERACTIONS; DRUG: ALBUTEROL SULFATE (PROAIR HFA) | SECTION: DOSAGE AND ADMINISTRATION; DRUG: ALBUTEROL SULFATE (PROAIR HFA) | SECTION: DRUG OVERVIEW & INDICATIONS
- ARTICLE_SECTION_LEAK (Bug E): False

- /answer: status=200 grounded=True err=''
- answer[:240]='LIMIT the dose of simvastatin in patients on amlodipine to 20 mg daily. Dose Counter: Displays 200 after priming. Pro Air HFA is a pressurized metered- dose aerosol unit'

### U3_amlo_simva
**Query:** What is the drug interaction between amlodipine and simvastatin, and what dose adjustment is required?
**Expected:** Amlodipine_Norvasc.pdf | KWs: [simvastatin, 20 mg]
**User symptom:** Partial answer; LLM said mechanism not detailed

- /analyze: retrieval_count=6 top_score=1.646 2nd=1.608
- citations=6 pages=[7, 2, 5, 4, 3, 13] expected_doc_in_top=True
- snippet_lens=[71, 112, 118, 71, 98, 95] truncated=[True, True, True, True, True, True]
- first_snippet[:160]='LIMIT the dose of simvastatin in patients on amlodipine to 20 mg daily.'
- expected_kw_in_snippets: simvastatin=Y, 20 mg=Y
- page_proofs=6 highlight_spans=6 highlight_chars=565 page_text_chars=7784
  -> highlight coverage: 7.3%
- section_titles[0:3]: DRUG: AMLODIPINE BESYLATE (NORVASC) | SECTION: DRUG INTERACTIONS; DRUG: AMLODIPINE BESYLATE (NORVASC) | SECTION: DOSAGE AND ADMINISTRATION | SUBSECTION: ADULTS; DRUG: AMLODIPINE BESYLATE (NORVASC) | SECTION: ADVERSE REACTIONS | SUBSECTION: CLINICAL TRIALS –
- ARTICLE_SECTION_LEAK (Bug E): False

- /answer: status=200 grounded=True err=''
- answer[:240]='LIMIT the dose of simvastatin in patients on amlodipine to 20 mg daily. Angina (Chronic Stable or Vasospastic): The recommended dose is 5 to 10 mg, with the lower dose suggested in the Drug: Amlodipine Besylate (Norvasc) | Section: Adverse '

### U4_lipitor_tipranavir
**Query:** Why is it not recommended to take Lipitor concurrently with tipranavir plus ritonavir?
**Expected:** Atorvastatin.pdf | KWs: [tipranavir, ritonavir]
**User symptom:** Possibly hallucinated CYP3A4 mechanism

- /analyze: retrieval_count=6 top_score=0.513 2nd=0.432
- citations=6 pages=[5, 3, 9, 2, 15, 12] expected_doc_in_top=True
- snippet_lens=[112, 38, 32, 72, 42, 84] truncated=[True, True, True, True, True, True]
- first_snippet[:160]='\x7f Concomitant use of cyclosporine, gemfibrozil, tipranavir plus ritonavir, or glecaprevir plus pibrentasvir with'
- expected_kw_in_snippets: tipranavir=Y, ritonavir=Y
- page_proofs=6 highlight_spans=6 highlight_chars=380 page_text_chars=10762
  -> highlight coverage: 3.5%
- section_titles[0:3]: DRUG: ATORVASTATIN (LIPITOR) | SECTION: WARNINGS AND PRECAUTIONS | SUBSECTION: MYOPATHY AND; DRUG: ATORVASTATIN (LIPITOR) | SECTION: DOSAGE AND ADMINISTRATION | SUBSECTION: DOSAGE MODIFICATIONS DUE; DRUG: ATORVASTATIN (LIPITOR) | SECTION: DRUG INTERACTIONS | SUBSECTION: DRUGS INCREASING RISK OF MYOPATHY
- ARTICLE_SECTION_LEAK (Bug E): False

- /answer: status=200 grounded=True err=''
- answer[:240]='\x7f Concomitant use of cyclosporine, gemfibrozil, tipranavir plus ritonavir, or glecaprevir plus pibrentasvir with'

### U5_synthroid_weight_loss
**Query:** What does the boxed warning state regarding the use of Synthroid for weight loss?
**Expected:** Levothyroxine.pdf | KWs: [obesity, weight loss]
**User symptom:** Correct (sanity check)

- /analyze: retrieval_count=6 top_score=0.488 2nd=0.340
- citations=6 pages=[1, 18, 11, 16, 2, 14] expected_doc_in_top=True
- snippet_lens=[58, 118, 85, 107, 94, 118] truncated=[True, True, True, True, True, True]
- first_snippet[:160]='BOXED WARNING: NOT FOR TREATMENT OF OBESITY OR WEIGHT LOSS'
- expected_kw_in_snippets: obesity=Y, weight loss=Y
- page_proofs=6 highlight_spans=6 highlight_chars=580 page_text_chars=10856
  -> highlight coverage: 5.3%
- section_titles[0:3]: DRUG: LEVOTHYROXINE SODIUM (SYNTHROID) | SECTION: BOXED WARNING AND INDICATIONS AND USAGE; DRUG: LEVOTHYROXINE SODIUM (SYNTHROID) | SECTION: OVERDOSAGE; DRUG: LEVOTHYROXINE SODIUM (SYNTHROID) | SECTION: ADVERSE REACTIONS
- ARTICLE_SECTION_LEAK (Bug E): False

- /answer: status=200 grounded=True err=''
- answer[:240]='BOXED WARNING: NOT FOR TREATMENT OF OBESITY OR WEIGHT LOSS'

### U6_metformin_renal
**Query:** In what specific scenario regarding renal function is Metformin extended-release contraindicated?
**Expected:** Metformin.pdf | KWs: [eGFR, 30]
**User symptom:** LLM said 'snippet truncates before detailing specific conditions'

- /analyze: retrieval_count=6 top_score=0.593 2nd=0.558
- citations=6 pages=[9, 2, 3, 11, 1, 7] expected_doc_in_top=True
- snippet_lens=[81, 114, 87, 80, 112, 96] truncated=[True, True, True, True, True, True]
- first_snippet[:160]='Metformin hydrochloride extended- release tablets are contraindicated in patients'
- expected_kw_in_snippets: eGFR=N, 30=N
- page_proofs=6 highlight_spans=6 highlight_chars=570 page_text_chars=9822
  -> highlight coverage: 5.8%
- section_titles[0:3]: DRUG: METFORMIN HYDROCHLORIDE (GLUCOPHAGE) | SECTION: USE IN SPECIFIC POPULATIONS | SUBSECTION; DRUG: METFORMIN HYDROCHLORIDE (GLUCOPHAGE) | SECTION: DOSAGE AND ADMINISTRATION | SUBSECTION: ADULT; DRUG: METFORMIN HYDROCHLORIDE (GLUCOPHAGE) | SECTION: CONTRAINDICATIONS
- ARTICLE_SECTION_LEAK (Bug E): False

- /answer: status=200 grounded=True err=''
- answer[:240]='Metformin hydrochloride extended- release tablets are contraindicated in patients'

### U7_omeprazole_alt_admin
**Query:** If a patient cannot swallow an intact omeprazole capsule, what is the alternative administration option?
**Expected:** Omeprazole.pdf | KWs: [applesauce, pellets]
**User symptom:** Correct, but section labeled 'Article 2' (Bug E)

- /analyze: retrieval_count=6 top_score=0.536 2nd=0.446
- citations=6 pages=[2, 4, 7, 10, 6, 1] expected_doc_in_top=True
- snippet_lens=[91, 108, 106, 107, 134, 90] truncated=[True, True, True, True, True, True]
- first_snippet[:160]='patients unable to swallow an intact capsule, see Alternative Administration Options (2.8).'
- expected_kw_in_snippets: applesauce=Y, pellets=Y
- page_proofs=6 highlight_spans=6 highlight_chars=636 page_text_chars=9795
  -> highlight coverage: 6.5%
- section_titles[0:3]: DRUG: OMEPRAZOLE DELAYED- RELEASE (PRILOSEC) | SECTION: DOSAGE AND ADMINISTRATION | SUBSECTION: ADULT; Article 2: Open the capsule and carefully empty ALL pellets onto the applesauce.; DRUG: OMEPRAZOLE DELAYED- RELEASE (PRILOSEC) | SECTION: WARNINGS AND PRECAUTIONS | SUBSECTION
- ARTICLE_SECTION_LEAK (Bug E): True

- /answer: status=200 grounded=True err=''
- answer[:240]='patients unable to swallow an intact capsule, see Alternative Administration Options (2.8). 3. Mix the pellets with the applesauce and swallow IMMEDIATELY with a glass of cool water to ensure complete If pregnancy occurs while taking clarit'

### U8_sertraline_serotonin_syndrome
**Query:** What are the neuromuscular and autonomic instability signs of Serotonin Syndrome?
**Expected:** Sertraline.pdf | KWs: [tremor, rigidity, myoclonus, tachycardia, diaphoresis]
**User symptom:** False negative — table on p.6 has the answer

- /analyze: retrieval_count=6 top_score=0.521 2nd=0.273
- citations=6 pages=[6, 5, 15, 10, 11, 7] expected_doc_in_top=True
- snippet_lens=[41, 36, 92, 118, 42, 90] truncated=[True, True, True, True, True, True]
- first_snippet[:160]='Signs and Symptoms of Serotonin Syndrome:'
- expected_kw_in_snippets: tremor=N, rigidity=N, myoclonus=N, tachycardia=N, diaphoresis=N
- page_proofs=6 highlight_spans=6 highlight_chars=419 page_text_chars=8940
  -> highlight coverage: 4.7%
- section_titles[0:3]: DRUG: SERTRALINE HYDROCHLORIDE (ZOLOFT) | SECTION: WARNINGS AND PRECAUTIONS | SUBSECTION: SUICIDALITY; DRUG: SERTRALINE HYDROCHLORIDE (ZOLOFT) | SECTION: CONTRAINDICATIONS; DRUG: SERTRALINE HYDROCHLORIDE (ZOLOFT) | SECTION: OVERDOSAGE
- ARTICLE_SECTION_LEAK (Bug E): False

- /answer: status=200 grounded=True err=''
- answer[:240]='Signs and Symptoms of Serotonin Syndrome: Increased risk of serotonin syndrome Contact a Poison Control Center (1- 800- 221- 2222) or a medical toxicologist for additional'

### P1_acet_max_adult_50kg
**Query:** What is the maximum daily dose of acetaminophen injection for an adult weighing 70 kg?
**Expected:** Acetaminophen.pdf | KWs: [4000 mg]
**User symptom:** Numeric (70) not in chunk; should still answer

- /analyze: retrieval_count=0 top_score=0.000 2nd=0.000
- citations=0 pages=[] expected_doc_in_top=False
- snippet_lens=[] truncated=[]
- first_snippet[:160]=''
- expected_kw_in_snippets: 4000 mg=N
- page_proofs=0 highlight_spans=0 highlight_chars=0 page_text_chars=0
  -> highlight coverage: 0.0%
- section_titles[0:3]: 
- ARTICLE_SECTION_LEAK (Bug E): False

- /answer: status=200 grounded=False err=''
- answer[:240]='I could not find grounded evidence for that request.'

### P2_acet_neonate
**Query:** What is the maximum daily dose for neonates receiving acetaminophen injection?
**Expected:** Acetaminophen.pdf | KWs: [50 mg/kg]
**User symptom:** Pediatric dosing chunk lookup

- /analyze: retrieval_count=6 top_score=1.757 2nd=1.708
- citations=6 pages=[3, 2, 4, 15, 17, 10] expected_doc_in_top=True
- snippet_lens=[37, 54, 87, 114, 116, 58] truncated=[True, True, True, True, True, True]
- first_snippet[:160]='Maximum daily dose: 75 mg/kg per day.'
- expected_kw_in_snippets: 50 mg/kg=N
- page_proofs=6 highlight_spans=6 highlight_chars=466 page_text_chars=8037
  -> highlight coverage: 5.8%
- section_titles[0:3]: DRUG: ACETAMINOPHEN INJECTION | SECTION: DOSAGE AND ADMINISTRATION | SUBSECTION: CHILDREN, NEONATES &; DRUG: ACETAMINOPHEN INJECTION | SECTION: DOSAGE AND ADMINISTRATION | SUBSECTION: ADULTS AND ADOLESCENTS; DRUG: ACETAMINOPHEN INJECTION | SECTION: DOSAGE AND ADMINISTRATION | SUBSECTION: INTRAVENOUS
- ARTICLE_SECTION_LEAK (Bug E): False

- /answer: status=200 grounded=True err=''
- answer[:240]='Maximum daily dose: 75 mg/kg per day.'

### P3_metformin_egfr_45
**Query:** Is metformin recommended for a patient with eGFR of 35 mL/min/1.73 m²?
**Expected:** Metformin.pdf | KWs: [30 to <45, not recommended]
**User symptom:** Range lookup with numeric (35)

- /analyze: retrieval_count=6 top_score=0.794 2nd=0.793
- citations=6 pages=[2, 9, 3, 10, 11, 14] expected_doc_in_top=True
- snippet_lens=[41, 34, 107, 119, 80, 98] truncated=[True, True, True, True, True, True]
- first_snippet[:160]='\x7f Patients with eGFR 30–60 mL/min/1.73 m²'
- expected_kw_in_snippets: 30 to <45=N, not recommended=N
- page_proofs=6 highlight_spans=6 highlight_chars=479 page_text_chars=10685
  -> highlight coverage: 4.5%
- section_titles[0:3]: DRUG: METFORMIN HYDROCHLORIDE (GLUCOPHAGE) | SECTION: DOSAGE AND ADMINISTRATION | SUBSECTION: ADULT; DRUG: METFORMIN HYDROCHLORIDE (GLUCOPHAGE) | SECTION: USE IN SPECIFIC POPULATIONS | SUBSECTION; DRUG: METFORMIN HYDROCHLORIDE (GLUCOPHAGE) | SECTION: CONTRAINDICATIONS
- ARTICLE_SECTION_LEAK (Bug E): False

- /answer: status=200 grounded=True err=''
- answer[:240]='\x7f Patients with eGFR 30–60 mL/min/1.73 m²'

### P4_metformin_lactic_acidosis_treatment
**Query:** How should suspected lactic acidosis from metformin be treated?
**Expected:** Metformin.pdf | KWs: [hemodialysis, discontinue]
**User symptom:** Multi-sentence answer in tables/paragraphs

- /analyze: retrieval_count=6 top_score=0.576 2nd=0.521
- citations=5 pages=[9, 1, 4, 3, 7] expected_doc_in_top=True
- snippet_lens=[119, 110, 74, 107, 37] truncated=[True, True, True, True, True]
- first_snippet[:160]='Use of metformin in patients with hepatic impairment has been associated with cases of lactic acidosis, possibly due to'
- expected_kw_in_snippets: hemodialysis=N, discontinue=Y
- page_proofs=5 highlight_spans=5 highlight_chars=447 page_text_chars=8372
  -> highlight coverage: 5.3%
- section_titles[0:3]: DRUG: METFORMIN HYDROCHLORIDE (GLUCOPHAGE) | SECTION: USE IN SPECIFIC POPULATIONS | SUBSECTION; DRUG: METFORMIN HYDROCHLORIDE (GLUCOPHAGE) | SECTION: BOXED WARNING AND INDICATIONS AND USAGE; Article 45: Reassess if eGFR falls below 45.
- ARTICLE_SECTION_LEAK (Bug E): True

- /answer: status=200 grounded=True err=''
- answer[:240]='Use of metformin in patients with hepatic impairment has been associated with cases of lactic acidosis, possibly due to'

### P5_sertraline_pregnancy_pphn
**Query:** What is the risk of PPHN with sertraline use in late pregnancy?
**Expected:** Sertraline.pdf | KWs: [6-fold, 20th week]
**User symptom:** Specific numeric fact

- /analyze: retrieval_count=6 top_score=0.633 2nd=0.442
- citations=6 pages=[12, 5, 7, 6, 8, 11] expected_doc_in_top=True
- snippet_lens=[119, 56, 98, 117, 122, 33] truncated=[True, True, True, True, True, True]
- first_snippet[:160]='Exposure to SSRIs including sertraline in late pregnancy may lead to increased risk of neonatal complications requiring'
- expected_kw_in_snippets: 6-fold=N, 20th week=N
- page_proofs=6 highlight_spans=6 highlight_chars=545 page_text_chars=9961
  -> highlight coverage: 5.5%
- section_titles[0:3]: DRUG: SERTRALINE HYDROCHLORIDE (ZOLOFT) | SECTION: USE IN SPECIFIC POPULATIONS | SUBSECTION: PREGNANCY; DRUG: SERTRALINE HYDROCHLORIDE (ZOLOFT) | SECTION: CONTRAINDICATIONS; DRUG: SERTRALINE HYDROCHLORIDE (ZOLOFT) | SECTION: WARNINGS AND PRECAUTIONS | SUBSECTION: BLEEDING,
- ARTICLE_SECTION_LEAK (Bug E): False

- /answer: status=200 grounded=True err=''
- answer[:240]='Exposure to SSRIs including sertraline in late pregnancy may lead to increased risk of neonatal complications requiring'

### P6_sertraline_maoi_washout
**Query:** How many days must elapse between stopping an MAOI and starting sertraline?
**Expected:** Sertraline.pdf | KWs: [14 days]
**User symptom:** Numeric anchor (14) appears verbatim

- /analyze: retrieval_count=6 top_score=0.637 2nd=0.636
- citations=6 pages=[11, 3, 5, 4, 8, 14] expected_doc_in_top=True
- snippet_lens=[41, 87, 32, 112, 122, 118] truncated=[True, True, True, True, True, True]
- first_snippet[:160]='elapse between stopping MAOI and starting'
- expected_kw_in_snippets: 14 days=Y
- page_proofs=6 highlight_spans=6 highlight_chars=512 page_text_chars=9725
  -> highlight coverage: 5.3%
- section_titles[0:3]: DRUG: SERTRALINE HYDROCHLORIDE (ZOLOFT) | SECTION: DRUG INTERACTIONS | SUBSECTION: CLINICALLY SIGNIFICANT; DRUG: SERTRALINE HYDROCHLORIDE (ZOLOFT) | SECTION: DOSAGE AND ADMINISTRATION | SUBSECTION: MDD, OCD, PD,; DRUG: SERTRALINE HYDROCHLORIDE (ZOLOFT) | SECTION: CONTRAINDICATIONS
- ARTICLE_SECTION_LEAK (Bug E): False

- /answer: status=200 grounded=True err=''
- answer[:240]='elapse between stopping MAOI and starting days must also elapse after stopping sertraline before starting an MAOI antidepressant. within 14 days of stopping MAOIs'

### P7_albuterol_priming
**Query:** When should the ProAir HFA inhaler be primed?
**Expected:** Albuterol.pdf | KWs: [3 sprays, 2 weeks, first time]
**User symptom:** Multi-condition list

- /analyze: retrieval_count=6 top_score=0.445 2nd=0.417
- citations=6 pages=[2, 10, 8, 9, 4, 13] expected_doc_in_top=True
- snippet_lens=[81, 103, 99, 101, 90, 100] truncated=[True, True, True, True, True, True]
- first_snippet[:160]='If the patient has more than one Pro Air HFA inhaler, wash each one separately to'
- expected_kw_in_snippets: 3 sprays=N, 2 weeks=N, first time=N
- page_proofs=6 highlight_spans=6 highlight_chars=574 page_text_chars=7653
  -> highlight coverage: 7.5%
- section_titles[0:3]: DRUG: ALBUTEROL SULFATE (PROAIR HFA) | SECTION: DOSAGE AND ADMINISTRATION; DRUG: ALBUTEROL SULFATE (PROAIR HFA) | SECTION: USE IN SPECIFIC POPULATIONS | SUBSECTION: GERIATRIC USE; DRUG: ALBUTEROL SULFATE (PROAIR HFA) | SECTION: USE IN SPECIFIC POPULATIONS | SUBSECTION: PREGNANCY
- ARTICLE_SECTION_LEAK (Bug E): False

- /answer: status=200 grounded=True err=''
- answer[:240]='If the patient has more than one Pro Air HFA inhaler, wash each one separately to'

### P8_omeprazole_indications
**Query:** What are the FDA-approved indications for omeprazole delayed-release capsules?
**Expected:** Omeprazole.pdf | KWs: [GERD]
**User symptom:** List answer

- /analyze: retrieval_count=6 top_score=0.577 2nd=0.537
- citations=6 pages=[1, 5, 2, 17, 7, 4] expected_doc_in_top=True
- snippet_lens=[109, 116, 67, 106, 125, 114] truncated=[True, True, True, True, True, True]
- first_snippet[:160]='Omeprazole delayed- release capsules is a proton pump inhibitor (PPI) indicated for the following conditions:'
- expected_kw_in_snippets: GERD=N
- page_proofs=6 highlight_spans=6 highlight_chars=637 page_text_chars=8926
  -> highlight coverage: 7.1%
- section_titles[0:3]: DRUG: OMEPRAZOLE DELAYED- RELEASE (PRILOSEC) | SECTION: INDICATIONS AND USAGE; DRUG: OMEPRAZOLE DELAYED- RELEASE (PRILOSEC) | SECTION: DOSAGE FORMS, STRENGTHS AND CONTRAINDICATIONS; DRUG: OMEPRAZOLE DELAYED- RELEASE (PRILOSEC) | SECTION: DOSAGE AND ADMINISTRATION | SUBSECTION: ADULT
- ARTICLE_SECTION_LEAK (Bug E): True

- /answer: status=200 grounded=True err=''
- answer[:240]='Omeprazole delayed- release capsules is a proton pump inhibitor (PPI) indicated for the following conditions:'

### P9_levo_overdose_symptoms
**Query:** What are the signs and symptoms of levothyroxine overdose?
**Expected:** Levothyroxine.pdf | KWs: [tachycardia, weight loss]
**User symptom:** Adverse-reaction list

- /analyze: retrieval_count=6 top_score=0.520 2nd=0.505
- citations=6 pages=[18, 9, 11, 8, 1, 7] expected_doc_in_top=True
- snippet_lens=[96, 72, 118, 133, 89, 107] truncated=[True, True, True, True, True, True]
- first_snippet[:160]='Reduce the SYNTHROID dosage or discontinue temporarily if signs or symptoms of overdosage occur.'
- expected_kw_in_snippets: tachycardia=N, weight loss=N
- page_proofs=6 highlight_spans=6 highlight_chars=615 page_text_chars=8443
  -> highlight coverage: 7.3%
- section_titles[0:3]: DRUG: LEVOTHYROXINE SODIUM (SYNTHROID) | SECTION: OVERDOSAGE; DRUG: LEVOTHYROXINE SODIUM (SYNTHROID) | SECTION: WARNINGS AND PRECAUTIONS | SUBSECTION: CARDIAC RISKS,; DRUG: LEVOTHYROXINE SODIUM (SYNTHROID) | SECTION: ADVERSE REACTIONS
- ARTICLE_SECTION_LEAK (Bug E): False

- /answer: status=200 grounded=True err=''
- answer[:240]='Reduce the SYNTHROID dosage or discontinue temporarily if signs or symptoms of overdosage occur. sympathomimetic agents for signs and symptoms of coronary insufficiency. angioedema, gastrointestinal symptoms (abdominal pain, nausea, vomitin'

### P10_atorva_pregnancy
**Query:** Is atorvastatin contraindicated in pregnancy?
**Expected:** Atorvastatin.pdf | KWs: [pregnancy, contraindicated]
**User symptom:** Yes/no with reason

- /analyze: retrieval_count=6 top_score=0.515 2nd=0.471
- citations=6 pages=[4, 13, 11, 2, 3, 8] expected_doc_in_top=True
- snippet_lens=[64, 134, 91, 117, 125, 117] truncated=[True, True, True, True, True, True]
- first_snippet[:160]='\x7f Hypersensitivity to atorvastatin or any excipients in LIPITOR.'
- expected_kw_in_snippets: pregnancy=Y, contraindicated=N
- page_proofs=6 highlight_spans=6 highlight_chars=648 page_text_chars=8848
  -> highlight coverage: 7.3%
- section_titles[0:3]: DRUG: ATORVASTATIN (LIPITOR) | SECTION: CONTRAINDICATIONS; DRUG: ATORVASTATIN (LIPITOR) | SECTION: USE IN SPECIFIC POPULATIONS | SUBSECTION: RENAL IMPAIRMENT, HEPATIC; DRUG: ATORVASTATIN (LIPITOR) | SECTION: USE IN SPECIFIC POPULATIONS | SUBSECTION: PREGNANCY
- ARTICLE_SECTION_LEAK (Bug E): False

- /answer: status=200 grounded=True err=''
- answer[:240]='\x7f Hypersensitivity to atorvastatin or any excipients in LIPITOR.'

### P11_sertraline_pediatric_indications
**Query:** Which sertraline indications are approved for pediatric patients?
**Expected:** Sertraline.pdf | KWs: [OCD]
**User symptom:** Single specific indication from table

- /analyze: retrieval_count=6 top_score=0.569 2nd=0.560
- citations=6 pages=[2, 13, 6, 10, 1, 3] expected_doc_in_top=True
- snippet_lens=[68, 110, 119, 122, 121, 124] truncated=[True, True, True, True, True, True]
- first_snippet[:160]='been established for MDD or other indications in pediatric patients.'
- expected_kw_in_snippets: OCD=Y
- page_proofs=6 highlight_spans=6 highlight_chars=664 page_text_chars=9011
  -> highlight coverage: 7.4%
- section_titles[0:3]: DRUG: SERTRALINE HYDROCHLORIDE (ZOLOFT) | SECTION: INDICATIONS AND USAGE; DRUG: SERTRALINE HYDROCHLORIDE (ZOLOFT) | SECTION: USE IN SPECIFIC POPULATIONS | SUBSECTION: LACTATION AND; DRUG: SERTRALINE HYDROCHLORIDE (ZOLOFT) | SECTION: WARNINGS AND PRECAUTIONS | SUBSECTION: SUICIDALITY
- ARTICLE_SECTION_LEAK (Bug E): False

- /answer: status=200 grounded=True err=''
- answer[:240]='been established for MDD or other indications in pediatric patients.'

### P12_compare_dosing_intervals
**Query:** What is the minimum dosing interval for acetaminophen injection in adults?
**Expected:** Acetaminophen.pdf | KWs: [4 hours]
**User symptom:** Specific fact

- /analyze: retrieval_count=6 top_score=0.668 2nd=0.615
- citations=6 pages=[2, 3, 14, 1, 8, 13] expected_doc_in_top=True
- snippet_lens=[114, 33, 120, 115, 89, 96] truncated=[True, True, True, True, True, True]
- first_snippet[:160]='adjustment is required when converting between oral acetaminophen and acetaminophen injection dosing in adults and'
- expected_kw_in_snippets: 4 hours=N
- page_proofs=6 highlight_spans=6 highlight_chars=567 page_text_chars=6952
  -> highlight coverage: 8.2%
- section_titles[0:3]: DRUG: ACETAMINOPHEN INJECTION | SECTION: DOSAGE AND ADMINISTRATION | SUBSECTION: ADULTS AND ADOLESCENTS; DRUG: ACETAMINOPHEN INJECTION | SECTION: DOSAGE AND ADMINISTRATION | SUBSECTION: CHILDREN, NEONATES &; DRUG: ACETAMINOPHEN INJECTION | SECTION: USE IN SPECIFIC POPULATIONS | SUBSECTION: GERIATRIC, HEPATIC &
- ARTICLE_SECTION_LEAK (Bug E): False

- /answer: status=200 grounded=True err=''
- answer[:240]='adjustment is required when converting between oral acetaminophen and acetaminophen injection dosing in adults and'


## Aggregate (20 queries)
- Expected doc in top citations: 18/20
- All expected keywords found in snippets: 6/20
- /answer 200: 19/20 | 404 (gate-rejected): 1/20 | 5xx: 0/20
- Article-section leak (Bug E): 3/20
- Queries with at least one truncated snippet (Bug D): 18/20
- Avg first snippet len: 70.7 chars
- Avg citations per query: 5.35
- Avg highlight coverage: 482.9 / 8153.0 chars = 5.92%

