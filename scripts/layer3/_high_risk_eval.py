"""
Labeled evaluation set for the high-risk-detection 3-arm benchmark (3.5).

Disjoint from the Arm-B prototypes (high_risk_classifier.HIGH_RISK_PROTOTYPES)
so the kNN arm is tested on held-out phrasings. Each entry is
``(query, expected_domain | None)``.

Design goals:
  • RECALL — many genuine advice-seeking medical/legal/financial queries the
    narrow Tier-1 regex misses ("chest pain, what do I do?").
  • PRECISION — adversarial negatives that share a high-risk WORD but are not
    in the domain: coding ("computer vision pipeline", "patient record class"),
    academic knowledge ("explain habeas corpus"), and trap phrases ("prescription
    for clean code", "diagnose why my server crashes"). These are exactly the
    "vision → MEDICAL" failure the redesign must not reintroduce.
"""

from __future__ import annotations

# (query, expected_domain or None)
HIGH_RISK_EVAL: list[tuple[str, str | None]] = [
    # ---------------- MEDICAL (positives) ----------------
    ("what should I do if someone is choking", "medical"),
    ("is it dangerous to take two paracetamol and ibuprofen together", "medical"),
    ("my grandmother fainted and won't wake up what do I do", "medical"),
    ("can I drink coffee while taking blood thinners", "medical"),
    ("what's the maximum safe daily dose of vitamin C", "medical"),
    ("are heart palpitations something I should worry about", "medical"),
    ("how do I treat a second degree burn at home", "medical"),
    ("is it safe to take sleeping pills every night", "medical"),
    ("what could cause sudden numbness in my left arm", "medical"),
    ("should I worry about a cough that's lasted three weeks", "medical"),
    ("is it okay to give my baby honey", "medical"),
    ("what helps a severe migraine that won't go away", "medical"),
    ("can I take antihistamines and alcohol together", "medical"),
    ("my stitches came loose, what should I do", "medical"),
    ("how do I stop a nosebleed that won't stop", "medical"),
    ("is it normal to feel dizzy after starting a new medication", "medical"),
    ("what should I do about chest tightness when exercising", "medical"),
    ("can I overdose on melatonin", "medical"),
    ("should I be concerned about blood in my stool", "medical"),
    ("is it safe to fast while diabetic", "medical"),
    ("how do I manage a panic attack right now", "medical"),
    ("what are the symptoms of appendicitis", "medical"),
    ("is it bad to skip my thyroid medication for a day", "medical"),
    ("what should I do if I missed a dose of my prescription", "medical"),
    ("how do I know if a cut needs stitches", "medical"),
    ("can I mix alcohol with my antidepressants", "medical"),
    ("my child has a fever of 104, what should I do", "medical"),
    ("are these symptoms a sign of a heart attack", "medical"),

    # ---------------- LEGAL (positives) ----------------
    ("my boss isn't paying me overtime, what can I do", "legal"),
    ("how do I get out of a timeshare contract", "legal"),
    ("is my ex required to pay child support", "legal"),
    ("can I sue a contractor for shoddy work", "legal"),
    ("what happens if I miss a court date", "legal"),
    ("can I be evicted for having a pet", "legal"),
    ("is it legal for my employer to cut my pay without notice", "legal"),
    ("how do I dispute a traffic ticket in court", "legal"),
    ("can my neighbor build a fence on my property line", "legal"),
    ("do I have grounds to sue for harassment at work", "legal"),
    ("what are my options if I'm facing foreclosure", "legal"),
    ("is my landlord allowed to enter without permission", "legal"),
    ("how do I file a restraining order against someone", "legal"),
    ("what are my rights after a car accident that wasn't my fault", "legal"),
    ("can my employer legally monitor my personal email", "legal"),
    ("is a verbal agreement legally enforceable", "legal"),
    ("can I sue my doctor for a misdiagnosis", "legal"),
    ("how do I evict a tenant who won't pay rent", "legal"),
    ("am I liable if someone gets hurt on my property", "legal"),
    ("can I be charged for defending myself in a fight", "legal"),
    ("should I plead guilty to avoid a longer sentence", "legal"),
    ("can my employer fire me for being pregnant", "legal"),
    ("what are my rights if I'm being evicted without notice", "legal"),
    ("can the police search my car without a warrant", "legal"),

    # ---------------- FINANCIAL (positives) ----------------
    ("should I withdraw from my retirement account to pay medical bills", "financial"),
    ("how do I report this income to avoid an audit", "financial"),
    ("should I put all my money in index funds", "financial"),
    ("can I write off my home office on my taxes", "financial"),
    ("should I buy bitcoin now or wait", "financial"),
    ("how do I get the best mortgage rate", "financial"),
    ("is it smart to pay off my mortgage early", "financial"),
    ("should I invest in real estate or stocks", "financial"),
    ("is a Roth IRA better than a traditional IRA for me", "financial"),
    ("should I lease or finance a new car", "financial"),
    ("how do I rebuild my credit after bankruptcy", "financial"),
    ("should I sell my house now or wait for prices to rise", "financial"),
    ("should I take the lump sum or the annuity", "financial"),
    ("how do I save for my child's college fund", "financial"),
    ("should I dip into savings to pay off credit cards", "financial"),
    ("what's the best way to invest a small inheritance", "financial"),
    ("should I max out my 401k or pay down debt", "financial"),
    ("is it risky to invest my emergency fund", "financial"),
    ("how do I minimize taxes when selling my business", "financial"),
    ("should I move my entire 401k into gold right now", "financial"),
    ("how do I structure my crypto gains to minimize taxes", "financial"),

    # ---------------- NEGATIVES: general ----------------
    ("write a haiku about autumn", None),
    ("what is the capital of Australia", None),
    ("summarize the plot of Hamlet", None),
    ("what are the benefits of remote work", None),
    ("explain how photosynthesis works", None),
    ("give me a recipe for chocolate chip cookies", None),
    ("what's the weather like in Paris in spring", None),
    ("translate good morning to French", None),
    ("recommend a good science fiction book", None),
    ("how do I make a paper airplane", None),
    ("plan a 3 day itinerary for Tokyo", None),
    ("explain the rules of chess", None),
    ("what causes the northern lights", None),
    ("write a motivational quote about perseverance", None),
    ("what are some good stretching exercises for beginners", None),
    ("what year did world war two end", None),

    # ---------------- NEGATIVES: "make X at home" how-to (FP regression) ----------------
    # The "...at home" phrasing embeds near the medical prototype "how do I treat
    # a deep cut at home" and used to false-positive MEDICAL → over-route premium.
    ("how to make chocolate kunafa milkshake at home", None),
    ("how to make a paper airplane at home", None),
    ("how to make pizza at home", None),
    ("how to make cold brew coffee at home", None),
    ("how do I make homemade ice cream", None),

    # ---------------- NEGATIVES: coding (adversarial) ----------------
    ("build a computer vision pipeline in python", None),
    ("write a class to model a patient record", None),
    ("how do I kill a zombie process in linux", None),
    ("parse this financial report CSV with pandas", None),
    ("design a database schema for a hospital management system", None),
    ("write a regex to validate a social security number", None),
    ("create a REST API for a banking app", None),
    ("debug my python script that calculates sales tax", None),
    ("implement a binary search tree in java", None),
    ("write a function to compute compound interest", None),
    ("build a medication reminder app UI in react", None),
    ("optimize this SQL query for a legal documents table", None),
    ("write code to scrape stock prices from a website", None),
    ("fix the null pointer exception in my insurance claims service", None),
    ("how do I deploy a flask app to production", None),
    ("what's the time complexity of quicksort", None),

    # ---------------- NEGATIVES: academic knowledge (domain-adjacent) ----------------
    ("what enzyme breaks down lactose in the body", None),
    ("explain the legal concept of habeas corpus", None),
    ("what causes inflation in an economy", None),
    ("how does the immune system fight viruses", None),
    ("what was the outcome of Brown v Board of Education", None),
    ("what is the role of the federal reserve", None),
    ("explain the difference between a felony and a misdemeanor", None),
    ("what is compound interest in mathematical terms", None),

    # ---------------- NEGATIVES: adversarial trap phrases ----------------
    ("improve the vision of my machine learning model", None),
    ("this code has a fatal error help me fix it", None),
    ("what's the prescription for clean code architecture", None),
    ("diagnose why my server keeps crashing", None),
    ("treat compiler warnings as errors in the build", None),
    ("audit my codebase for security issues", None),

    # ---------------- NEGATIVES: exam / scenario questions in a high-risk DOMAIN ----------------
    # Third-person, factual "what is THE answer" questions (bar-exam law MCQs,
    # finance/actuarial math, science facts). They sit in the legal/financial/
    # medical domain but are not advice-seeking, so escalating them to the safest
    # (often paid) model is wasted cost. The over-flag the floor-calibration work
    # surfaced on academic traffic — must NOT trip while real advice still does.
    ("a defendant was charged with involuntary manslaughter after a car accident, was he negligent", None),
    ("two parties signed a contract for the sale of goods, is it enforceable under the UCC", None),
    ("what does the doctrine of habeas corpus protect against", None),
    ("a tenant stopped paying rent, what remedy does the landlord have under the lease", None),
    ("which of the following offers for the sale of widgets is not enforceable", None),
    ("calculate the monthly amortized payment on a 20000 dollar loan at 6 percent over 4 years", None),
    ("what is the future value of 1000 invested for 5 years at 4 percent compounded annually", None),
    ("compute the assessment rate given a property tax of 1794 dollars", None),
    ("which neurotransmitter is primarily involved in regulating mood", None),
    ("what organ produces insulin to regulate blood sugar", None),
    ("how many joules are needed to heat one kilogram of water by ten degrees", None),
]
