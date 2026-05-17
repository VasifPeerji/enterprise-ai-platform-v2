# RAG diagnostic against `test-docs4`
_2026-05-08 00:52:53_

### U1_acet_45kg
**Query:** What is the maximum daily dose of acetaminophen injection for an adult weighing 45 kg?
**Expected:** Acetaminophen.pdf | KWs: [75 mg/kg, 3750 mg]
**User symptom:** False negative ('No relevant knowledge found')

- /analyze: retrieval_count=6 top_score=1.733 2nd=1.698
- citations=6 pages=[2, 3, 4, 15, 17, 8] expected_doc_in_top=True
- snippet_lens=[699, 620, 696, 595, 699, 687] truncated=[True, True, True, True, True, True]
- first_snippet[:160]='2.2 Recommended Dosage: Adults and Adolescents Adults and adolescents weighing 50 kg and over: 1000 mg every 6 hours OR 650 mg every 4 hours. Maximum single dos'
- expected_kw_in_snippets: 75 mg/kg=Y, 3750 mg=Y
- expected_kw_in_proofs:   75 mg/kg=Y, 3750 mg=Y
- page_proofs=6 highlight_spans=71 highlight_chars=8284 page_text_chars=8229
  -> highlight coverage: 100.7%
- section_titles[0:3]: DRUG: ACETAMINOPHEN INJECTION | SECTION: DOSAGE AND ADMINISTRATION | SUBSECTION: ADULTS AND ADOLESCENTS; DRUG: ACETAMINOPHEN INJECTION | SECTION: DOSAGE AND ADMINISTRATION | SUBSECTION: CHILDREN, NEONATES &; DRUG: ACETAMINOPHEN INJECTION | SECTION: DOSAGE AND ADMINISTRATION | SUBSECTION: INTRAVENOUS
- ARTICLE_SECTION_LEAK (Bug E): False

- /answer: status=200 grounded=True err=''
- answer[:240]='2.2 Recommended Dosage: Adults and Adolescents Adults and adolescents weighing 50 kg and over: 1000 mg every 6 hours OR 650 mg every 4 hours. Maximum single dose: 1000 mg. Minimum dosing interval: 4 hours. Maximum daily dose: 4000 mg per da'

### U2_proair_dose_counter
**Query:** How does the dose counter on the ProAir HFA inhaler work, and when should the inhaler be discarded?
**Expected:** Albuterol.pdf | KWs: [200, 20, RED, discard, expiration]
**User symptom:** Grounded query failed

- /analyze: retrieval_count=6 top_score=1.357 2nd=1.339
- citations=6 pages=[7, 2, 1, 4, 2, 3] expected_doc_in_top=True
- snippet_lens=[683, 700, 645, 593, 688, 681] truncated=[True, True, True, True, True, True]
- first_snippet[:160]='agent independently exerted its own blood pressure lowering effect. 7.2 Impact of Amlodipine on Other Drugs Simvastatin: Co- administration of multiple doses of'
- expected_kw_in_snippets: 200=Y, 20=Y, RED=Y, discard=Y, expiration=Y
- expected_kw_in_proofs:   200=Y, 20=Y, RED=Y, discard=Y, expiration=Y
- page_proofs=6 highlight_spans=72 highlight_chars=7004 page_text_chars=9378
  -> highlight coverage: 74.7%
- section_titles[0:3]: DRUG: AMLODIPINE BESYLATE (NORVASC) | SECTION: DRUG INTERACTIONS; DRUG: ALBUTEROL SULFATE (PROAIR HFA) | SECTION: DOSAGE AND ADMINISTRATION; DRUG: ALBUTEROL SULFATE (PROAIR HFA) | SECTION: DRUG OVERVIEW & INDICATIONS
- ARTICLE_SECTION_LEAK (Bug E): False

- /answer: status=200 grounded=True err=''
- answer[:240]='agent independently exerted its own blood pressure lowering effect. 7.2 Impact of Amlodipine on Other Drugs Simvastatin: Co- administration of multiple doses of amlodipine 10 mg with simvastatin 80 mg resulted in a 77% increase in exposure '

### U3_amlo_simva
**Query:** What is the drug interaction between amlodipine and simvastatin, and what dose adjustment is required?
**Expected:** Amlodipine_Norvasc.pdf | KWs: [simvastatin, 20 mg]
**User symptom:** Partial answer; LLM said mechanism not detailed

- /analyze: retrieval_count=6 top_score=1.646 2nd=1.608
- citations=6 pages=[7, 2, 5, 4, 3, 13] expected_doc_in_top=True
- snippet_lens=[683, 690, 623, 628, 692, 693] truncated=[True, True, True, True, True, True]
- first_snippet[:160]='agent independently exerted its own blood pressure lowering effect. 7.2 Impact of Amlodipine on Other Drugs Simvastatin: Co- administration of multiple doses of'
- expected_kw_in_snippets: simvastatin=Y, 20 mg=Y
- expected_kw_in_proofs:   simvastatin=Y, 20 mg=Y
- page_proofs=6 highlight_spans=72 highlight_chars=8571 page_text_chars=7784
  -> highlight coverage: 110.1%
- section_titles[0:3]: DRUG: AMLODIPINE BESYLATE (NORVASC) | SECTION: DRUG INTERACTIONS; DRUG: AMLODIPINE BESYLATE (NORVASC) | SECTION: DOSAGE AND ADMINISTRATION | SUBSECTION: ADULTS; DRUG: AMLODIPINE BESYLATE (NORVASC) | SECTION: ADVERSE REACTIONS | SUBSECTION: CLINICAL TRIALS –
- ARTICLE_SECTION_LEAK (Bug E): False

- /answer: status=200 grounded=True err=''
- answer[:240]='agent independently exerted its own blood pressure lowering effect. 7.2 Impact of Amlodipine on Other Drugs Simvastatin: Co- administration of multiple doses of amlodipine 10 mg with simvastatin 80 mg resulted in a 77% increase in exposure '

### U4_lipitor_tipranavir
**Query:** Why is it not recommended to take Lipitor concurrently with tipranavir plus ritonavir?
**Expected:** Atorvastatin.pdf | KWs: [tipranavir, ritonavir]
**User symptom:** Possibly hallucinated CYP3A4 mechanism

- /analyze: retrieval_count=6 top_score=0.513 2nd=0.432
- citations=6 pages=[5, 3, 9, 2, 15, 12] expected_doc_in_top=True
- snippet_lens=[661, 698, 691, 690, 696, 640] truncated=[True, True, True, True, True, True]
- first_snippet[:160]='lipid- lowering therapies), and higher LIPITOR dosage. Prevention and Management: \x7f LIPITOR exposure may be significantly increased by inhibition of CYP3A4 and/'
- expected_kw_in_snippets: tipranavir=Y, ritonavir=Y
- expected_kw_in_proofs:   tipranavir=Y, ritonavir=Y
- page_proofs=6 highlight_spans=72 highlight_chars=8107 page_text_chars=10762
  -> highlight coverage: 75.3%
- section_titles[0:3]: DRUG: ATORVASTATIN (LIPITOR) | SECTION: WARNINGS AND PRECAUTIONS | SUBSECTION: MYOPATHY AND; DRUG: ATORVASTATIN (LIPITOR) | SECTION: DOSAGE AND ADMINISTRATION | SUBSECTION: DOSAGE MODIFICATIONS DUE; DRUG: ATORVASTATIN (LIPITOR) | SECTION: DRUG INTERACTIONS | SUBSECTION: DRUGS INCREASING RISK OF MYOPATHY
- ARTICLE_SECTION_LEAK (Bug E): False

- /answer: status=200 grounded=True err=''
- answer[:240]='lipid- lowering therapies), and higher LIPITOR dosage. Prevention and Management: \x7f LIPITOR exposure may be significantly increased by inhibition of CYP3A4 and/or transporters (BCRP, OATP1B1/1B3, P- gp), increasing the risk of myopathy. \x7f C'

### U5_synthroid_weight_loss
**Query:** What does the boxed warning state regarding the use of Synthroid for weight loss?
**Expected:** Levothyroxine.pdf | KWs: [obesity, weight loss]
**User symptom:** Correct (sanity check)

- /analyze: retrieval_count=6 top_score=0.488 2nd=0.340
- citations=6 pages=[1, 18, 11, 16, 2, 14] expected_doc_in_top=True
- snippet_lens=[638, 670, 694, 633, 664, 700] truncated=[True, True, True, True, True, True]
- first_snippet[:160]='DRUG: LEVOTHYROXINE SODIUM (SYNTHROID) | SECTION: BOXED WARNING AND INDICATIONS AND USAGE Drug: Levothyroxine Sodium (Synthroid) | Section: Boxed Warning and In'
- expected_kw_in_snippets: obesity=Y, weight loss=Y
- expected_kw_in_proofs:   obesity=Y, weight loss=Y
- page_proofs=6 highlight_spans=72 highlight_chars=9091 page_text_chars=10856
  -> highlight coverage: 83.7%
- section_titles[0:3]: DRUG: LEVOTHYROXINE SODIUM (SYNTHROID) | SECTION: BOXED WARNING AND INDICATIONS AND USAGE; DRUG: LEVOTHYROXINE SODIUM (SYNTHROID) | SECTION: OVERDOSAGE; DRUG: LEVOTHYROXINE SODIUM (SYNTHROID) | SECTION: ADVERSE REACTIONS
- ARTICLE_SECTION_LEAK (Bug E): False

- /answer: status=200 grounded=True err=''
- answer[:240]='DRUG: LEVOTHYROXINE SODIUM (SYNTHROID) | SECTION: BOXED WARNING AND INDICATIONS AND USAGE Drug: Levothyroxine Sodium (Synthroid) | Section: Boxed Warning and Indications and Usage BOXED WARNING: NOT FOR TREATMENT OF OBESITY OR WEIGHT LOSS T'

### U6_metformin_renal
**Query:** In what specific scenario regarding renal function is Metformin extended-release contraindicated?
**Expected:** Metformin.pdf | KWs: [eGFR, 30]
**User symptom:** LLM said 'snippet truncates before detailing specific conditions'

- /analyze: retrieval_count=6 top_score=0.593 2nd=0.558
- citations=6 pages=[9, 2, 11, 3, 1, 7] expected_doc_in_top=True
- snippet_lens=[700, 670, 700, 509, 595, 683] truncated=[True, True, True, False, True, True]
- first_snippet[:160]='concomitant disease, and other drug therapy, and the higher risk of lactic acidosis. Assess renal function more frequently in elderly patients. 8.6 Renal Impair'
- expected_kw_in_snippets: eGFR=Y, 30=Y
- expected_kw_in_proofs:   eGFR=Y, 30=Y
- page_proofs=6 highlight_spans=66 highlight_chars=8096 page_text_chars=9822
  -> highlight coverage: 82.4%
- section_titles[0:3]: DRUG: METFORMIN HYDROCHLORIDE (GLUCOPHAGE) | SECTION: USE IN SPECIFIC POPULATIONS | SUBSECTION; DRUG: METFORMIN HYDROCHLORIDE (GLUCOPHAGE) | SECTION: DOSAGE AND ADMINISTRATION | SUBSECTION: ADULT; DRUG: METFORMIN HYDROCHLORIDE (GLUCOPHAGE) | SECTION: CLINICAL PHARMACOLOGY | SUBSECTION
- ARTICLE_SECTION_LEAK (Bug E): False

- /answer: status=200 grounded=True err=''
- answer[:240]='concomitant disease, and other drug therapy, and the higher risk of lactic acidosis. Assess renal function more frequently in elderly patients. 8.6 Renal Impairment Metformin is substantially excreted by the kidney, and the risk of metformi'

### U7_omeprazole_alt_admin
**Query:** If a patient cannot swallow an intact omeprazole capsule, what is the alternative administration option?
**Expected:** Omeprazole.pdf | KWs: [applesauce, pellets]
**User symptom:** Correct, but section labeled 'Article 2' (Bug E)

- /analyze: retrieval_count=6 top_score=0.569 2nd=0.536
- citations=6 pages=[4, 2, 7, 10, 6, 1] expected_doc_in_top=True
- snippet_lens=[695, 691, 695, 692, 666, 700] truncated=[True, True, True, True, True, True]
- first_snippet[:160]='10 kg to < 20 kg 10 mg Once daily ≥ 20 kg 20 mg Once daily On a per kg basis, doses of omeprazole required to heal erosive esophagitis in pediatric patients are'
- expected_kw_in_snippets: applesauce=Y, pellets=Y
- expected_kw_in_proofs:   applesauce=Y, pellets=Y
- page_proofs=6 highlight_spans=69 highlight_chars=8860 page_text_chars=9795
  -> highlight coverage: 90.5%
- section_titles[0:3]: DRUG: OMEPRAZOLE DELAYED- RELEASE (PRILOSEC) | SECTION: DOSAGE AND ADMINISTRATION | SUBSECTION: PEDIATRIC; DRUG: OMEPRAZOLE DELAYED- RELEASE (PRILOSEC) | SECTION: DOSAGE AND ADMINISTRATION | SUBSECTION: ADULT; DRUG: OMEPRAZOLE DELAYED- RELEASE (PRILOSEC) | SECTION: WARNINGS AND PRECAUTIONS | SUBSECTION
- ARTICLE_SECTION_LEAK (Bug E): False

- /answer: status=200 grounded=True err=''
- answer[:240]='10 kg to < 20 kg 10 mg Once daily ≥ 20 kg 20 mg Once daily On a per kg basis, doses of omeprazole required to heal erosive esophagitis in pediatric patients are greater than those for adults. Alternative administrative options can be used f'

### U8_sertraline_serotonin_syndrome
**Query:** What are the neuromuscular and autonomic instability signs of Serotonin Syndrome?
**Expected:** Sertraline.pdf | KWs: [tremor, rigidity, myoclonus, tachycardia, diaphoresis]
**User symptom:** False negative — table on p.6 has the answer

- /analyze: retrieval_count=6 top_score=0.521 2nd=0.273
- citations=6 pages=[6, 5, 15, 10, 11, 7] expected_doc_in_top=True
- snippet_lens=[699, 690, 674, 647, 689, 667] truncated=[True, True, True, True, True, True]
- first_snippet[:160]='5.2 Serotonin Syndrome SSRIs including sertraline can precipitate serotonin syndrome, a potentially life- threatening condition. Risk is increased with concomit'
- expected_kw_in_snippets: tremor=Y, rigidity=Y, myoclonus=Y, tachycardia=Y, diaphoresis=Y
- expected_kw_in_proofs:   tremor=Y, rigidity=Y, myoclonus=Y, tachycardia=Y, diaphoresis=Y
- page_proofs=6 highlight_spans=72 highlight_chars=8270 page_text_chars=8940
  -> highlight coverage: 92.5%
- section_titles[0:3]: DRUG: SERTRALINE HYDROCHLORIDE (ZOLOFT) | SECTION: WARNINGS AND PRECAUTIONS | SUBSECTION: SUICIDALITY; DRUG: SERTRALINE HYDROCHLORIDE (ZOLOFT) | SECTION: CONTRAINDICATIONS; DRUG: SERTRALINE HYDROCHLORIDE (ZOLOFT) | SECTION: OVERDOSAGE
- ARTICLE_SECTION_LEAK (Bug E): False

- /answer: status=200 grounded=True err=''
- answer[:240]='5.2 Serotonin Syndrome SSRIs including sertraline can precipitate serotonin syndrome, a potentially life- threatening condition. Risk is increased with concomitant use of other serotonergic drugs (triptans, TCAs, fentanyl, lithium, tramadol'

### P1_acet_max_adult_50kg
**Query:** What is the maximum daily dose of acetaminophen injection for an adult weighing 70 kg?
**Expected:** Acetaminophen.pdf | KWs: [4000 mg]
**User symptom:** Numeric (70) not in chunk; should still answer

- /analyze: retrieval_count=6 top_score=1.733 2nd=1.698
- citations=6 pages=[2, 3, 4, 15, 17, 8] expected_doc_in_top=True
- snippet_lens=[699, 620, 696, 595, 699, 687] truncated=[True, True, True, True, True, True]
- first_snippet[:160]='2.2 Recommended Dosage: Adults and Adolescents Adults and adolescents weighing 50 kg and over: 1000 mg every 6 hours OR 650 mg every 4 hours. Maximum single dos'
- expected_kw_in_snippets: 4000 mg=Y
- expected_kw_in_proofs:   4000 mg=Y
- page_proofs=6 highlight_spans=71 highlight_chars=8284 page_text_chars=8229
  -> highlight coverage: 100.7%
- section_titles[0:3]: DRUG: ACETAMINOPHEN INJECTION | SECTION: DOSAGE AND ADMINISTRATION | SUBSECTION: ADULTS AND ADOLESCENTS; DRUG: ACETAMINOPHEN INJECTION | SECTION: DOSAGE AND ADMINISTRATION | SUBSECTION: CHILDREN, NEONATES &; DRUG: ACETAMINOPHEN INJECTION | SECTION: DOSAGE AND ADMINISTRATION | SUBSECTION: INTRAVENOUS
- ARTICLE_SECTION_LEAK (Bug E): False

- /answer: status=200 grounded=True err=''
- answer[:240]='2.2 Recommended Dosage: Adults and Adolescents Adults and adolescents weighing 50 kg and over: 1000 mg every 6 hours OR 650 mg every 4 hours. Maximum single dose: 1000 mg. Minimum dosing interval: 4 hours. Maximum daily dose: 4000 mg per da'

### P2_acet_neonate
**Query:** What is the maximum daily dose for neonates receiving acetaminophen injection?
**Expected:** Acetaminophen.pdf | KWs: [50 mg/kg]
**User symptom:** Pediatric dosing chunk lookup

- /analyze: retrieval_count=6 top_score=1.757 2nd=1.708
- citations=6 pages=[3, 2, 4, 15, 17, 10] expected_doc_in_top=True
- snippet_lens=[620, 699, 665, 595, 699, 639] truncated=[True, True, True, True, True, True]
- first_snippet[:160]='DRUG: ACETAMINOPHEN INJECTION | SECTION: DOSAGE AND ADMINISTRATION | SUBSECTION: CHILDREN, NEONATES & INFANTS Drug: Acetaminophen Injection | Section: Dosage an'
- expected_kw_in_snippets: 50 mg/kg=N
- expected_kw_in_proofs:   50 mg/kg=Y
- page_proofs=6 highlight_spans=72 highlight_chars=8257 page_text_chars=8037
  -> highlight coverage: 102.7%
- section_titles[0:3]: DRUG: ACETAMINOPHEN INJECTION | SECTION: DOSAGE AND ADMINISTRATION | SUBSECTION: CHILDREN, NEONATES &; DRUG: ACETAMINOPHEN INJECTION | SECTION: DOSAGE AND ADMINISTRATION | SUBSECTION: ADULTS AND ADOLESCENTS; DRUG: ACETAMINOPHEN INJECTION | SECTION: DOSAGE AND ADMINISTRATION | SUBSECTION: INTRAVENOUS
- ARTICLE_SECTION_LEAK (Bug E): False

- /answer: status=200 grounded=True err=''
- answer[:240]='DRUG: ACETAMINOPHEN INJECTION | SECTION: DOSAGE AND ADMINISTRATION | SUBSECTION: CHILDREN, NEONATES & INFANTS Drug: Acetaminophen Injection | Section: Dosage and Administration | Subsection: Children, Neonates & Infants 2.3 Recommended Dosa'

### P3_metformin_egfr_45
**Query:** Is metformin recommended for a patient with eGFR of 35 mL/min/1.73 m²?
**Expected:** Metformin.pdf | KWs: [30 to <45, not recommended]
**User symptom:** Range lookup with numeric (35)

- /analyze: retrieval_count=6 top_score=0.794 2nd=0.793
- citations=6 pages=[2, 9, 3, 10, 11, 14] expected_doc_in_top=True
- snippet_lens=[699, 687, 509, 693, 694, 698] truncated=[True, True, False, True, True, True]
- first_snippet[:160]='<30 CONTRAINDICATED — do not use; discontinue if eGFR falls below 30 Assess renal function with eGFR prior to initiation and at least annually thereafter. In el'
- expected_kw_in_snippets: 30 to <45=N, not recommended=Y
- expected_kw_in_proofs:   30 to <45=Y, not recommended=Y
- page_proofs=6 highlight_spans=66 highlight_chars=7762 page_text_chars=10685
  -> highlight coverage: 72.6%
- section_titles[0:3]: DRUG: METFORMIN HYDROCHLORIDE (GLUCOPHAGE) | SECTION: DOSAGE AND ADMINISTRATION | SUBSECTION: ADULT; DRUG: METFORMIN HYDROCHLORIDE (GLUCOPHAGE) | SECTION: USE IN SPECIFIC POPULATIONS | SUBSECTION; DRUG: METFORMIN HYDROCHLORIDE (GLUCOPHAGE) | SECTION: CONTRAINDICATIONS
- ARTICLE_SECTION_LEAK (Bug E): False

- /answer: status=200 grounded=True err=''
- answer[:240]='<30 CONTRAINDICATED — do not use; discontinue if eGFR falls below 30 Assess renal function with eGFR prior to initiation and at least annually thereafter. In elderly patients and those at increased risk for renal impairment, assess renal fu'

### P4_metformin_lactic_acidosis_treatment
**Query:** How should suspected lactic acidosis from metformin be treated?
**Expected:** Metformin.pdf | KWs: [hemodialysis, discontinue]
**User symptom:** Multi-sentence answer in tables/paragraphs

- /analyze: retrieval_count=6 top_score=0.576 2nd=0.543
- citations=6 pages=[9, 4, 1, 3, 7, 11] expected_doc_in_top=True
- snippet_lens=[656, 698, 670, 509, 698, 677] truncated=[True, True, True, False, True, True]
- first_snippet[:160]='8.6 Renal Impairment with the degree of renal impairment. Metformin hydrochloride extended- release tablets are contraindicated in patients with eGFR below 30 m'
- expected_kw_in_snippets: hemodialysis=Y, discontinue=Y
- expected_kw_in_proofs:   hemodialysis=Y, discontinue=Y
- page_proofs=6 highlight_spans=66 highlight_chars=7392 page_text_chars=10394
  -> highlight coverage: 71.1%
- section_titles[0:3]: DRUG: METFORMIN HYDROCHLORIDE (GLUCOPHAGE) | SECTION: USE IN SPECIFIC POPULATIONS | SUBSECTION; DRUG: METFORMIN HYDROCHLORIDE (GLUCOPHAGE) | SECTION: WARNINGS AND PRECAUTIONS | SUBSECTION: LACTIC; DRUG: METFORMIN HYDROCHLORIDE (GLUCOPHAGE) | SECTION: BOXED WARNING AND INDICATIONS AND USAGE
- ARTICLE_SECTION_LEAK (Bug E): False

- /answer: status=200 grounded=True err=''
- answer[:240]='8.6 Renal Impairment with the degree of renal impairment. Metformin hydrochloride extended- release tablets are contraindicated in patients with eGFR below 30 mL/min/1.73 m². 8.7 Hepatic Impairment Use of metformin in patients with hepatic '

### P5_sertraline_pregnancy_pphn
**Query:** What is the risk of PPHN with sertraline use in late pregnancy?
**Expected:** Sertraline.pdf | KWs: [6-fold, 20th week]
**User symptom:** Specific numeric fact

- /analyze: retrieval_count=6 top_score=0.633 2nd=0.442
- citations=6 pages=[12, 5, 7, 6, 8, 11] expected_doc_in_top=True
- snippet_lens=[677, 664, 648, 673, 692, 698] truncated=[True, True, True, True, True, True]
- first_snippet[:160]='difference in major birth defect risk compared to the background rate. A meta- analysis suggests no increase in total malformations (OR=1.01, 95% CI 0.88–1.17) '
- expected_kw_in_snippets: 6-fold=N, 20th week=N
- expected_kw_in_proofs:   6-fold=N, 20th week=Y
- page_proofs=6 highlight_spans=72 highlight_chars=8768 page_text_chars=9961
  -> highlight coverage: 88.0%
- section_titles[0:3]: DRUG: SERTRALINE HYDROCHLORIDE (ZOLOFT) | SECTION: USE IN SPECIFIC POPULATIONS | SUBSECTION: PREGNANCY; DRUG: SERTRALINE HYDROCHLORIDE (ZOLOFT) | SECTION: CONTRAINDICATIONS; DRUG: SERTRALINE HYDROCHLORIDE (ZOLOFT) | SECTION: WARNINGS AND PRECAUTIONS | SUBSECTION: BLEEDING,
- ARTICLE_SECTION_LEAK (Bug E): False

- /answer: status=200 grounded=True err=''
- answer[:240]='difference in major birth defect risk compared to the background rate. A meta- analysis suggests no increase in total malformations (OR=1.01, 95% CI 0.88–1.17) or cardiac malformations (OR=0.93, 95% CI 0.70–1.23). Third Trimester Exposure —'

### P6_sertraline_maoi_washout
**Query:** How many days must elapse between stopping an MAOI and starting sertraline?
**Expected:** Sertraline.pdf | KWs: [14 days]
**User symptom:** Numeric anchor (14) appears verbatim

- /analyze: retrieval_count=6 top_score=0.637 2nd=0.636
- citations=6 pages=[11, 3, 5, 4, 8, 14] expected_doc_in_top=True
- snippet_lens=[696, 688, 690, 695, 692, 651] truncated=[True, True, True, True, True, True]
- first_snippet[:160]='DRUG INTERACTIONS Drug: Sertraline Hydrochloride (Zoloft) | Section: Drug Interactions | Subsection: Clinically Significant Drug Interactions 7.1 Clinically Sig'
- expected_kw_in_snippets: 14 days=Y
- expected_kw_in_proofs:   14 days=Y
- page_proofs=6 highlight_spans=72 highlight_chars=8181 page_text_chars=9725
  -> highlight coverage: 84.1%
- section_titles[0:3]: DRUG: SERTRALINE HYDROCHLORIDE (ZOLOFT) | SECTION: DRUG INTERACTIONS | SUBSECTION: CLINICALLY SIGNIFICANT; DRUG: SERTRALINE HYDROCHLORIDE (ZOLOFT) | SECTION: DOSAGE AND ADMINISTRATION | SUBSECTION: MDD, OCD, PD,; DRUG: SERTRALINE HYDROCHLORIDE (ZOLOFT) | SECTION: CONTRAINDICATIONS
- ARTICLE_SECTION_LEAK (Bug E): False

- /answer: status=200 grounded=True err=''
- answer[:240]='DRUG INTERACTIONS Drug: Sertraline Hydrochloride (Zoloft) | Section: Drug Interactions | Subsection: Clinically Significant Drug Interactions 7.1 Clinically Significant Drug Interactions Drug / Drug Class Clinical Impact Intervention MAOIs '

### P7_albuterol_priming
**Query:** When should the ProAir HFA inhaler be primed?
**Expected:** Albuterol.pdf | KWs: [3 sprays, 2 weeks, first time]
**User symptom:** Multi-condition list

- /analyze: retrieval_count=6 top_score=0.445 2nd=0.417
- citations=6 pages=[2, 10, 8, 9, 4, 13] expected_doc_in_top=True
- snippet_lens=[699, 647, 665, 687, 673, 597] truncated=[True, True, True, True, True, True]
- first_snippet[:160]='Administer Pro Air HFA by oral inhalation ONLY. Shake well before each spray. Priming: Prime the inhaler before using for the first time and in cases where the '
- expected_kw_in_snippets: 3 sprays=Y, 2 weeks=Y, first time=Y
- expected_kw_in_proofs:   3 sprays=Y, 2 weeks=Y, first time=Y
- page_proofs=6 highlight_spans=72 highlight_chars=9028 page_text_chars=7653
  -> highlight coverage: 118.0%
- section_titles[0:3]: DRUG: ALBUTEROL SULFATE (PROAIR HFA) | SECTION: DOSAGE AND ADMINISTRATION; DRUG: ALBUTEROL SULFATE (PROAIR HFA) | SECTION: USE IN SPECIFIC POPULATIONS | SUBSECTION: GERIATRIC USE; DRUG: ALBUTEROL SULFATE (PROAIR HFA) | SECTION: USE IN SPECIFIC POPULATIONS | SUBSECTION: PREGNANCY
- ARTICLE_SECTION_LEAK (Bug E): False

- /answer: status=200 grounded=True err=''
- answer[:240]='Administer Pro Air HFA by oral inhalation ONLY. Shake well before each spray. Priming: Prime the inhaler before using for the first time and in cases where the inhaler has not been used for more than 2 weeks, by releasing 3 sprays into the '

### P8_omeprazole_indications
**Query:** What are the FDA-approved indications for omeprazole delayed-release capsules?
**Expected:** Omeprazole.pdf | KWs: [GERD]
**User symptom:** List answer

- /analyze: retrieval_count=6 top_score=0.577 2nd=0.537
- citations=6 pages=[1, 5, 15, 4, 2, 17] expected_doc_in_top=True
- snippet_lens=[697, 669, 694, 666, 691, 651] truncated=[True, False, True, True, True, True]
- first_snippet[:160]='DRUG: OMEPRAZOLE DELAYED- RELEASE (PRILOSEC) | SECTION: INDICATIONS AND USAGE Drug: Omeprazole Delayed- Release (Prilosec) | Section: Indications and Usage 1. I'
- expected_kw_in_snippets: GERD=N
- expected_kw_in_proofs:   GERD=Y
- page_proofs=6 highlight_spans=67 highlight_chars=8315 page_text_chars=9481
  -> highlight coverage: 87.7%
- section_titles[0:3]: DRUG: OMEPRAZOLE DELAYED- RELEASE (PRILOSEC) | SECTION: INDICATIONS AND USAGE; DRUG: OMEPRAZOLE DELAYED- RELEASE (PRILOSEC) | SECTION: DOSAGE FORMS, STRENGTHS AND CONTRAINDICATIONS; DRUG: OMEPRAZOLE DELAYED- RELEASE (PRILOSEC) | SECTION: DESCRIPTION
- ARTICLE_SECTION_LEAK (Bug E): False

- /answer: status=200 grounded=True err=''
- answer[:240]='DRUG: OMEPRAZOLE DELAYED- RELEASE (PRILOSEC) | SECTION: INDICATIONS AND USAGE Drug: Omeprazole Delayed- Release (Prilosec) | Section: Indications and Usage 1. INDICATIONS AND USAGE Omeprazole delayed- release capsules is a proton pump inhib'

### P9_levo_overdose_symptoms
**Query:** What are the signs and symptoms of levothyroxine overdose?
**Expected:** Levothyroxine.pdf | KWs: [tachycardia, weight loss]
**User symptom:** Adverse-reaction list

- /analyze: retrieval_count=6 top_score=0.520 2nd=0.505
- citations=6 pages=[18, 9, 11, 8, 1, 7] expected_doc_in_top=True
- snippet_lens=[628, 664, 676, 641, 638, 694] truncated=[True, True, True, True, True, True]
- first_snippet[:160]='Signs and Symptoms of Hyperthyroid Overdosage: Arrhythmias, myocardial infarction, dyspnea, muscle spasm, headache, nervousness, irritability, insomnia, tremors'
- expected_kw_in_snippets: tachycardia=N, weight loss=Y
- expected_kw_in_proofs:   tachycardia=Y, weight loss=Y
- page_proofs=6 highlight_spans=64 highlight_chars=8402 page_text_chars=8443
  -> highlight coverage: 99.5%
- section_titles[0:3]: DRUG: LEVOTHYROXINE SODIUM (SYNTHROID) | SECTION: OVERDOSAGE; DRUG: LEVOTHYROXINE SODIUM (SYNTHROID) | SECTION: WARNINGS AND PRECAUTIONS | SUBSECTION: CARDIAC RISKS,; DRUG: LEVOTHYROXINE SODIUM (SYNTHROID) | SECTION: ADVERSE REACTIONS
- ARTICLE_SECTION_LEAK (Bug E): False

- /answer: status=200 grounded=True err=''
- answer[:240]='Signs and Symptoms of Hyperthyroid Overdosage: Arrhythmias, myocardial infarction, dyspnea, muscle spasm, headache, nervousness, irritability, insomnia, tremors, muscle weakness, increased appetite, weight loss, diarrhea, heat intolerance, '

### P10_atorva_pregnancy
**Query:** Is atorvastatin contraindicated in pregnancy?
**Expected:** Atorvastatin.pdf | KWs: [pregnancy, contraindicated]
**User symptom:** Yes/no with reason

- /analyze: retrieval_count=6 top_score=0.515 2nd=0.471
- citations=6 pages=[4, 13, 11, 2, 3, 8] expected_doc_in_top=True
- snippet_lens=[505, 691, 688, 652, 699, 675] truncated=[False, True, True, True, True, True]
- first_snippet[:160]='DRUG: ATORVASTATIN (LIPITOR) | SECTION: CONTRAINDICATIONS\nDrug: Atorvastatin (Lipitor) | Section: Contraindications\n4. CONTRAINDICATIONS\nLIPITOR is contraindica'
- expected_kw_in_snippets: pregnancy=Y, contraindicated=Y
- expected_kw_in_proofs:   pregnancy=Y, contraindicated=Y
- page_proofs=6 highlight_spans=67 highlight_chars=8178 page_text_chars=8848
  -> highlight coverage: 92.4%
- section_titles[0:3]: DRUG: ATORVASTATIN (LIPITOR) | SECTION: CONTRAINDICATIONS; DRUG: ATORVASTATIN (LIPITOR) | SECTION: USE IN SPECIFIC POPULATIONS | SUBSECTION: RENAL IMPAIRMENT, HEPATIC; DRUG: ATORVASTATIN (LIPITOR) | SECTION: USE IN SPECIFIC POPULATIONS | SUBSECTION: PREGNANCY
- ARTICLE_SECTION_LEAK (Bug E): False

- /answer: status=200 grounded=True err=''
- answer[:240]='DRUG: ATORVASTATIN (LIPITOR) | SECTION: CONTRAINDICATIONS\nDrug: Atorvastatin (Lipitor) | Section: Contraindications\n4. CONTRAINDICATIONS\nLIPITOR is contraindicated in patients with:\n\x7f Acute liver failure or decompensated cirrhosis [see Warn'

### P11_sertraline_pediatric_indications
**Query:** Which sertraline indications are approved for pediatric patients?
**Expected:** Sertraline.pdf | KWs: [OCD]
**User symptom:** Single specific indication from table

- /analyze: retrieval_count=6 top_score=0.569 2nd=0.560
- citations=6 pages=[2, 13, 6, 10, 1, 3] expected_doc_in_top=True
- snippet_lens=[684, 648, 623, 694, 677, 698] truncated=[True, True, True, True, True, True]
- first_snippet[:160]='following conditions in adults (and OCD in pediatric patients aged 6–17): Indication Abbreviation Patient Population Major Depressive Disorder MDD Adults Obsess'
- expected_kw_in_snippets: OCD=Y
- expected_kw_in_proofs:   OCD=Y
- page_proofs=6 highlight_spans=71 highlight_chars=7959 page_text_chars=9011
  -> highlight coverage: 88.3%
- section_titles[0:3]: DRUG: SERTRALINE HYDROCHLORIDE (ZOLOFT) | SECTION: INDICATIONS AND USAGE; DRUG: SERTRALINE HYDROCHLORIDE (ZOLOFT) | SECTION: USE IN SPECIFIC POPULATIONS | SUBSECTION: LACTATION AND; DRUG: SERTRALINE HYDROCHLORIDE (ZOLOFT) | SECTION: WARNINGS AND PRECAUTIONS | SUBSECTION: SUICIDALITY
- ARTICLE_SECTION_LEAK (Bug E): False

- /answer: status=200 grounded=True err=''
- answer[:240]='following conditions in adults (and OCD in pediatric patients aged 6–17): Indication Abbreviation Patient Population Major Depressive Disorder MDD Adults Obsessive- Compulsive Disorder OCD Adults and pediatric patients ages 6–17 Panic Disor'

### P12_compare_dosing_intervals
**Query:** What is the minimum dosing interval for acetaminophen injection in adults?
**Expected:** Acetaminophen.pdf | KWs: [4 hours]
**User symptom:** Specific fact

- /analyze: retrieval_count=6 top_score=0.668 2nd=0.615
- citations=6 pages=[2, 3, 14, 1, 8, 13] expected_doc_in_top=True
- snippet_lens=[658, 664, 673, 687, 687, 621] truncated=[True, True, True, True, True, True]
- first_snippet[:160]='Drug: Acetaminophen Injection | Section: Dosage and Administration | Subsection: Adults and Adolescents 2. DOSAGE AND ADMINISTRATION 2.1 General Dosing Informat'
- expected_kw_in_snippets: 4 hours=N
- expected_kw_in_proofs:   4 hours=Y
- page_proofs=6 highlight_spans=70 highlight_chars=8251 page_text_chars=6952
  -> highlight coverage: 118.7%
- section_titles[0:3]: DRUG: ACETAMINOPHEN INJECTION | SECTION: DOSAGE AND ADMINISTRATION | SUBSECTION: ADULTS AND ADOLESCENTS; DRUG: ACETAMINOPHEN INJECTION | SECTION: DOSAGE AND ADMINISTRATION | SUBSECTION: CHILDREN, NEONATES &; DRUG: ACETAMINOPHEN INJECTION | SECTION: USE IN SPECIFIC POPULATIONS | SUBSECTION: GERIATRIC, HEPATIC &
- ARTICLE_SECTION_LEAK (Bug E): False

- /answer: status=200 grounded=True err=''
- answer[:240]='Drug: Acetaminophen Injection | Section: Dosage and Administration | Subsection: Adults and Adolescents 2. DOSAGE AND ADMINISTRATION 2.1 General Dosing Information Acetaminophen injection may be given as a single or repeated dose for the tr'


## Aggregate (20 queries)
- Expected doc in top citations: 20/20
- All expected keywords found in snippets: 14/20
- All expected keywords found in snippets+page_proofs: 19/20
- /answer 200: 20/20 | 404 (gate-rejected): 0/20 | 5xx: 0/20
- Article-section leak (Bug E): 0/20
- Queries with at least one truncated snippet (Bug D): 20/20
- Avg first snippet len: 668.8 chars
- Avg citations per query: 6.00
- Avg highlight coverage: 8253.0 / 9149.2 chars = 90.20%
