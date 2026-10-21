"""Seed FABRICATED demo questions so the learner app can be developed and
demoed before the first real PYQ scan is ingested.

These are NOT real UPSC past questions. They are invented, plausible-looking
placeholders written to exercise the real code paths: bilingual text, LaTeX,
Prelims MCQ options with an answer key, topic tags, rankings, an A1 analysis
and a published one-pager. Every row is marked `session='demo'` so it can be
identified and removed.

Refuses to run outside KASAUTI_ENV=dev. Idempotent — re-running wipes and
recreates the demo rows.

    uv run python scripts/seed_demo_questions.py           # seed
    uv run python scripts/seed_demo_questions.py --wipe    # remove, seed nothing
"""

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "src"))

from kasauti_api.db.base import async_session_factory  # noqa: E402
from kasauti_api.db.models import (  # noqa: E402
    Paper,
    Question,
    QuestionEmbedding,
    QuestionOption,
    QuestionTopicMap,
    SourceScan,
    Topic,
    TopicAnalysis,
    TopicNote,
)
from kasauti_api.db.models.cost_ledger import LlmFeature  # noqa: E402
from kasauti_api.db.models.intelligence import AnalysisScope, TopicNoteStatus  # noqa: E402
from kasauti_api.db.models.questions import (  # noqa: E402
    OcrStatus,
    QuestionLanguage,
    QuestionStatus,
    TaggedBy,
)
from kasauti_api.domain.llm.cost_ledger import record_usage  # noqa: E402
from kasauti_api.domain.llm.embedding_provider import get_embedding_provider  # noqa: E402
from kasauti_api.settings import get_settings  # noqa: E402

DEMO_SESSION = "demo"  # the marker that makes these rows removable


# --- fabricated corpus -------------------------------------------------------
# (topic ltree path, year, question number, marks, English text, Hindi text, LaTeX)

MAINS_GS2: list[tuple[str, int, str, float, str, str]] = [
    ("gs2.constitution.basic_structure", 2016, "1", 12.5,
     "The doctrine of basic structure has evolved through judicial interpretation rather than "
     "constitutional text. Examine this evolution and its implications for parliamentary "
     "sovereignty.",
     "मूल संरचना का सिद्धांत संवैधानिक पाठ के बजाय न्यायिक व्याख्या के माध्यम से विकसित हुआ है। "
     "इस विकास तथा संसदीय संप्रभुता पर इसके निहितार्थों का परीक्षण कीजिए।"),
    ("gs2.constitution.basic_structure", 2019, "2", 15.0,
     "'The basic structure doctrine is a judicial innovation that has protected constitutional "
     "identity.' Critically evaluate in the light of recent constitutional amendments.",
     "'मूल संरचना सिद्धांत एक न्यायिक नवाचार है जिसने संवैधानिक पहचान की रक्षा की है।' हाल के "
     "संविधान संशोधनों के आलोक में आलोचनात्मक मूल्यांकन कीजिए।"),
    ("gs2.constitution.basic_structure", 2023, "3", 10.0,
     "Discuss whether the basic structure doctrine places an unreasonable limitation on the "
     "amending power of Parliament under Article 368.",
     "चर्चा कीजिए कि क्या मूल संरचना सिद्धांत अनुच्छेद 368 के अंतर्गत संसद की संशोधन शक्ति पर "
     "अनुचित सीमा आरोपित करता है।"),
    ("gs2.constitution.federalism", 2017, "4", 12.5,
     "Cooperative federalism has been more an aspiration than a working reality in Centre-State "
     "fiscal relations. Comment.",
     "केंद्र-राज्य वित्तीय संबंधों में सहकारी संघवाद एक कार्यशील वास्तविकता से अधिक एक आकांक्षा "
     "रही है। टिप्पणी कीजिए।"),
    ("gs2.constitution.federalism", 2020, "5", 15.0,
     "Examine the changing nature of Indian federalism in the context of the Goods and Services "
     "Tax Council and the devolution recommended by successive Finance Commissions.",
     "वस्तु एवं सेवा कर परिषद तथा क्रमिक वित्त आयोगों द्वारा संस्तुत हस्तांतरण के संदर्भ में भारतीय "
     "संघवाद की बदलती प्रकृति का परीक्षण कीजिए।"),
    ("gs2.constitution.federalism", 2024, "6", 10.0,
     "Do you agree that asymmetric federalism weakens the uniformity of the Indian Union? "
     "Substantiate your view.",
     "क्या आप सहमत हैं कि असममित संघवाद भारतीय संघ की एकरूपता को कमज़ोर करता है? अपने मत की "
     "पुष्टि कीजिए।"),
    ("gs2.polity.parliament", 2018, "7", 12.5,
     "The declining number of sittings and the frequent use of the ordinance route have eroded "
     "parliamentary oversight. Discuss with examples.",
     "बैठकों की घटती संख्या तथा अध्यादेश मार्ग के बारंबार प्रयोग ने संसदीय निगरानी को क्षीण किया "
     "है। उदाहरणों सहित चर्चा कीजिए।"),
    ("gs2.polity.parliament", 2022, "8", 15.0,
     "Parliamentary committees are described as 'mini-Parliaments'. Assess their effectiveness in "
     "scrutinising executive action.",
     "संसदीय समितियों को 'लघु संसद' कहा जाता है। कार्यपालिका की कार्रवाई की जाँच में उनकी "
     "प्रभावशीलता का आकलन कीजिए।"),
    ("gs2.polity.executive_judiciary", 2019, "9", 10.0,
     "Judicial appointments in India have oscillated between executive primacy and collegium "
     "supremacy. Trace this trajectory and suggest a way forward.",
     "भारत में न्यायिक नियुक्तियाँ कार्यपालिका की प्रधानता तथा कॉलेजियम की सर्वोच्चता के बीच "
     "दोलन करती रही हैं। इस प्रक्षेप-पथ का अनुरेखण कीजिए और आगे की राह सुझाइए।"),
    ("gs2.polity.executive_judiciary", 2023, "10", 15.0,
     "'Judicial activism, when it substitutes for policy-making, risks becoming judicial "
     "overreach.' Critically examine.",
     "'न्यायिक सक्रियता, जब वह नीति-निर्माण का स्थान ले लेती है, न्यायिक अतिक्रमण बनने का जोखिम "
     "उठाती है।' आलोचनात्मक परीक्षण कीजिए।"),
    ("gs2.governance.transparency_accountability", 2017, "11", 12.5,
     "Has the Right to Information Act delivered on its promise of accountable governance? "
     "Evaluate with reference to institutional capacity.",
     "क्या सूचना का अधिकार अधिनियम ने जवाबदेह शासन के अपने वादे को पूरा किया है? संस्थागत क्षमता "
     "के संदर्भ में मूल्यांकन कीजिए।"),
    ("gs2.governance.transparency_accountability", 2021, "12", 10.0,
     "E-governance improves service delivery but can deepen exclusion. Discuss with reference to "
     "Aadhaar-linked welfare delivery.",
     "ई-गवर्नेंस सेवा प्रदायगी में सुधार करता है किंतु बहिष्करण को गहरा कर सकता है। आधार-संबद्ध "
     "कल्याण प्रदायगी के संदर्भ में चर्चा कीजिए।"),
    ("gs2.governance.welfare_schemes", 2018, "13", 15.0,
     "Direct benefit transfers have reduced leakage but not necessarily improved outcomes for "
     "vulnerable sections. Examine.",
     "प्रत्यक्ष लाभ अंतरण ने रिसाव कम किया है किंतु कमज़ोर वर्गों के परिणामों में आवश्यक रूप से "
     "सुधार नहीं किया है। परीक्षण कीजिए।"),
    ("gs2.governance.welfare_schemes", 2024, "14", 10.0,
     "Assess the role of convergence between welfare schemes in improving last-mile delivery.",
     "अंतिम छोर तक प्रदायगी सुधारने में कल्याणकारी योजनाओं के बीच अभिसरण की भूमिका का आकलन कीजिए।"),
    ("gs2.social_justice.health_education", 2020, "15", 12.5,
     "The pandemic exposed structural weaknesses in India's public health architecture. Discuss "
     "the reforms needed at the primary care level.",
     "महामारी ने भारत की सार्वजनिक स्वास्थ्य संरचना की संरचनात्मक कमज़ोरियों को उजागर किया। "
     "प्राथमिक देखभाल स्तर पर आवश्यक सुधारों की चर्चा कीजिए।"),
    ("gs2.social_justice.health_education", 2023, "16", 15.0,
     "Examine the equity implications of the shift towards outcome-based funding in school "
     "education.",
     "विद्यालयी शिक्षा में परिणाम-आधारित वित्तपोषण की ओर बदलाव के समता-संबंधी निहितार्थों का "
     "परीक्षण कीजिए।"),
    ("gs2.international_relations.india_neighbourhood", 2019, "17", 15.0,
     "India's neighbourhood policy has struggled to balance strategic autonomy with regional "
     "connectivity. Critically analyse.",
     "भारत की पड़ोस नीति सामरिक स्वायत्तता तथा क्षेत्रीय संपर्क के बीच संतुलन साधने में संघर्ष "
     "करती रही है। आलोचनात्मक विश्लेषण कीजिए।"),
    ("gs2.international_relations.india_neighbourhood", 2022, "18", 10.0,
     "Discuss the significance of the 'Neighbourhood First' policy in the context of growing "
     "external influence in South Asia.",
     "दक्षिण एशिया में बढ़ते बाह्य प्रभाव के संदर्भ में 'पड़ोसी पहले' नीति के महत्व की चर्चा कीजिए।"),
    ("gs2.international_relations.groupings_agreements", 2021, "19", 15.0,
     "Assess India's evolving role in plurilateral groupings and what it signals about its "
     "non-alignment tradition.",
     "बहुपक्षीय समूहों में भारत की विकसित होती भूमिका तथा यह उसकी गुटनिरपेक्षता परंपरा के विषय "
     "में क्या संकेत देती है, इसका आकलन कीजिए।"),
    ("gs2.international_relations.international_institutions", 2024, "20", 12.5,
     "Reform of multilateral institutions has stalled despite broad agreement on its necessity. "
     "Examine the reasons.",
     "आवश्यकता पर व्यापक सहमति के बावजूद बहुपक्षीय संस्थानों का सुधार ठप पड़ा है। कारणों का "
     "परीक्षण कीजिए।"),
]

MAINS_MATHS: list[tuple[str, int, str, float, str, str, str]] = [
    ("maths1.linear_algebra.eigenvalues_eigenvectors", 2017, "1(a)", 10.0,
     "Find the eigenvalues and eigenvectors of the matrix A and verify the Cayley-Hamilton "
     "theorem.",
     "आव्यूह A के आइगेनमान एवं आइगेनसदिश ज्ञात कीजिए तथा केली–हैमिल्टन प्रमेय का सत्यापन कीजिए।",
     r"A = \begin{pmatrix} 2 & 1 & 0 \\ 0 & 3 & 1 \\ 0 & 0 & 2 \end{pmatrix}"),
    ("maths1.linear_algebra.eigenvalues_eigenvectors", 2020, "2(b)", 15.0,
     "Show that a real symmetric matrix is diagonalisable and that its eigenvalues are real.",
     "दर्शाइए कि एक वास्तविक सममित आव्यूह विकर्णनीय होता है तथा उसके आइगेनमान वास्तविक होते हैं।",
     r"A = A^{T},\ A \in \mathbb{R}^{n \times n}"),
    ("maths1.linear_algebra.eigenvalues_eigenvectors", 2023, "1(c)", 10.0,
     "Determine the characteristic polynomial of the given matrix and hence compute its inverse "
     "using the Cayley-Hamilton theorem.",
     "दिए गए आव्यूह का अभिलक्षणिक बहुपद निर्धारित कीजिए तथा केली–हैमिल्टन प्रमेय का उपयोग करके "
     "उसका प्रतिलोम परिकलित कीजिए।",
     r"p(\lambda) = \det(A - \lambda I)"),
    ("maths1.linear_algebra.vector_spaces", 2018, "1(b)", 10.0,
     "Prove that any two bases of a finite-dimensional vector space have the same number of "
     "elements.",
     "सिद्ध कीजिए कि किसी परिमित-विमीय सदिश समष्टि के किन्हीं दो आधारों में अवयवों की संख्या "
     "समान होती है।",
     r"\dim(V) = |B_1| = |B_2|"),
    ("maths1.linear_algebra.linear_transformations", 2022, "2(a)", 15.0,
     "State and prove the rank-nullity theorem for a linear transformation between "
     "finite-dimensional vector spaces.",
     "परिमित-विमीय सदिश समष्टियों के बीच एक रैखिक रूपांतरण के लिए कोटि-शून्यता प्रमेय का कथन "
     "एवं उपपत्ति दीजिए।",
     r"\dim(V) = \operatorname{rank}(T) + \operatorname{nullity}(T)"),
    ("maths1.calculus.riemann_integral", 2019, "3(a)", 15.0,
     "Test the convergence of the given improper integral and evaluate it where it converges.",
     "दिए गए अनुचित समाकल के अभिसरण का परीक्षण कीजिए तथा जहाँ यह अभिसरित होता है वहाँ इसका "
     "मान ज्ञात कीजिए।",
     r"\int_{0}^{\infty} \frac{\sin x}{x}\,dx"),
    ("maths1.calculus.several_variables", 2021, "3(b)", 10.0,
     "Using Lagrange's method of multipliers, find the extreme values subject to the given "
     "constraint.",
     "लाग्रांज गुणक विधि का उपयोग करते हुए, दिए गए प्रतिबंध के अधीन चरम मान ज्ञात कीजिए।",
     r"f(x,y,z) = x^2 + y^2 + z^2,\quad x + y + z = 1"),
    ("maths1.calculus.several_variables", 2024, "3(c)", 15.0,
     "Compute the Jacobian of the given transformation and state the condition for functional "
     "dependence.",
     "दिए गए रूपांतरण का जैकोबियन परिकलित कीजिए तथा फलनात्मक निर्भरता की शर्त बताइए।",
     r"J = \frac{\partial(u,v)}{\partial(x,y)}"),
    ("maths1.calculus.mean_value_theorems", 2020, "4(a)", 10.0,
     "State Taylor's theorem with Lagrange's form of remainder and use it to expand the given "
     "function.",
     "लाग्रांज शेषफल रूप के साथ टेलर प्रमेय का कथन दीजिए तथा इसका उपयोग करके दिए गए फलन का "
     "प्रसार कीजिए।",
     r"f(x) = f(a) + f'(a)(x-a) + \frac{f''(a)}{2!}(x-a)^2 + \cdots"),
    ("maths1.analytic_geometry.sphere_cone_cylinder", 2018, "4(b)", 15.0,
     "Find the equation of the sphere passing through the given points and determine its centre "
     "and radius.",
     "दिए गए बिंदुओं से गुजरने वाले गोले का समीकरण ज्ञात कीजिए तथा उसका केंद्र एवं त्रिज्या "
     "निर्धारित कीजिए।",
     r"x^2 + y^2 + z^2 + 2ux + 2vy + 2wz + d = 0"),
    ("maths1.ordinary_differential_equations.first_order", 2022, "5(a)", 10.0,
     "Solve the given first order differential equation using an appropriate integrating factor.",
     "उपयुक्त समाकलन गुणक का उपयोग करते हुए दिए गए प्रथम कोटि अवकल समीकरण को हल कीजिए।",
     r"\frac{dy}{dx} + P(x)y = Q(x),\quad \mu(x) = e^{\int P\,dx}"),
    ("maths1.ordinary_differential_equations.first_order", 2024, "5(b)", 15.0,
     "Obtain the general and singular solutions of Clairaut's equation for the given form.",
     "दिए गए रूप के लिए क्लेरो समीकरण के व्यापक एवं विचित्र हल प्राप्त कीजिए।",
     r"y = px + f(p),\quad p = \frac{dy}{dx}"),
]

# (topic path, year, q.no, en, hi, [(label, en, hi)], correct_label)
PRELIMS_GS1: list[tuple[str, int, str, str, str, list[tuple[str, str, str]], str]] = [
    ("gs2.constitution.basic_structure", 2019, "12",
     "Which one of the following is NOT regarded as part of the basic structure of the "
     "Constitution of India?",
     "निम्नलिखित में से कौन-सा भारत के संविधान की मूल संरचना का भाग नहीं माना जाता है?",
     [("A", "Judicial review", "न्यायिक पुनरावलोकन"),
      ("B", "Free and fair elections", "स्वतंत्र एवं निष्पक्ष निर्वाचन"),
      ("C", "Right to property", "संपत्ति का अधिकार"),
      ("D", "Separation of powers", "शक्तियों का पृथक्करण")],
     "C"),
    ("gs2.constitution.basic_structure", 2022, "18",
     "With reference to the amending procedure of the Constitution of India, consider the "
     "statements above. Which of the statements given above is/are correct?",
     "भारत के संविधान की संशोधन प्रक्रिया के संदर्भ में, ऊपर दिए गए कथनों पर विचार कीजिए। ऊपर "
     "दिए गए कथनों में से कौन-सा/से सही है/हैं?",
     [("A", "1 only", "केवल 1"),
      ("B", "2 only", "केवल 2"),
      ("C", "Both 1 and 2", "1 और 2 दोनों"),
      ("D", "Neither 1 nor 2", "न तो 1 और न ही 2")],
     "C"),
    ("gs2.constitution.federalism", 2018, "24",
     "Which of the following bodies has been constituted to recommend the distribution of net "
     "proceeds of taxes between the Union and the States?",
     "संघ एवं राज्यों के बीच करों की शुद्ध आगमों के वितरण की संस्तुति हेतु निम्नलिखित में से कौन-सा "
     "निकाय गठित किया गया है?",
     [("A", "NITI Aayog", "नीति आयोग"),
      ("B", "Finance Commission", "वित्त आयोग"),
      ("C", "Inter-State Council", "अंतर-राज्य परिषद"),
      ("D", "GST Council", "जीएसटी परिषद")],
     "B"),
    ("gs2.constitution.federalism", 2021, "31",
     "Consider the following with reference to the Goods and Services Tax Council. How many of "
     "the above statements are correct?",
     "वस्तु एवं सेवा कर परिषद के संदर्भ में निम्नलिखित पर विचार कीजिए। उपर्युक्त कथनों में से कितने "
     "सही हैं?",
     [("A", "Only one", "केवल एक"),
      ("B", "Only two", "केवल दो"),
      ("C", "All three", "सभी तीन"),
      ("D", "None", "कोई नहीं")],
     "B"),
    ("gs2.constitution.federalism", 2024, "9",
     "Which one of the following best describes 'asymmetric federalism' as practised in India?",
     "निम्नलिखित में से कौन-सा भारत में व्यवहृत 'असममित संघवाद' का सर्वोत्तम वर्णन करता है?",
     [("A", "Equal powers to all States", "सभी राज्यों को समान शक्तियाँ"),
      ("B", "Differential constitutional arrangements for certain States",
       "कुछ राज्यों हेतु विभेदक संवैधानिक व्यवस्थाएँ"),
      ("C", "Exclusive Union control over State subjects",
       "राज्य विषयों पर संघ का अनन्य नियंत्रण"),
      ("D", "Abolition of the State List", "राज्य सूची का उन्मूलन")],
     "B"),
    ("gs2.polity.parliament", 2017, "45",
     "Which of the following is a financial committee of Parliament?",
     "निम्नलिखित में से कौन-सी संसद की एक वित्तीय समिति है?",
     [("A", "Committee on Government Assurances", "सरकारी आश्वासनों संबंधी समिति"),
      ("B", "Public Accounts Committee", "लोक लेखा समिति"),
      ("C", "Committee on Petitions", "याचिका समिति"),
      ("D", "Business Advisory Committee", "कार्य मंत्रणा समिति")],
     "B"),
    ("gs2.polity.parliament", 2020, "27",
     "The power to promulgate ordinances is available to the President under which Article of "
     "the Constitution of India?",
     "अध्यादेश प्रख्यापित करने की शक्ति राष्ट्रपति को भारत के संविधान के किस अनुच्छेद के अंतर्गत "
     "प्राप्त है?",
     [("A", "Article 121", "अनुच्छेद 121"),
      ("B", "Article 123", "अनुच्छेद 123"),
      ("C", "Article 213", "अनुच्छेद 213"),
      ("D", "Article 356", "अनुच्छेद 356")],
     "B"),
    ("gs2.polity.executive_judiciary", 2019, "52",
     "The collegium system of judicial appointments derives from which of the following?",
     "न्यायिक नियुक्तियों की कॉलेजियम प्रणाली निम्नलिखित में से किससे व्युत्पन्न है?",
     [("A", "An express provision of the Constitution", "संविधान का एक स्पष्ट उपबंध"),
      ("B", "A parliamentary statute", "एक संसदीय अधिनियम"),
      ("C", "Judicial interpretation", "न्यायिक व्याख्या"),
      ("D", "A constitutional convention alone", "केवल एक संवैधानिक परिपाटी")],
     "C"),
    ("gs2.polity.constitutional_bodies", 2023, "38",
     "Which one of the following is NOT a constitutional body?",
     "निम्नलिखित में से कौन-सा एक संवैधानिक निकाय नहीं है?",
     [("A", "Election Commission of India", "भारत निर्वाचन आयोग"),
      ("B", "Comptroller and Auditor General", "नियंत्रक एवं महालेखापरीक्षक"),
      ("C", "National Human Rights Commission", "राष्ट्रीय मानवाधिकार आयोग"),
      ("D", "Union Public Service Commission", "संघ लोक सेवा आयोग")],
     "C"),
    ("gs2.governance.transparency_accountability", 2018, "61",
     "Under the Right to Information Act, 2005, which of the following is exempt from "
     "disclosure?",
     "सूचना का अधिकार अधिनियम, 2005 के अंतर्गत निम्नलिखित में से कौन-सा प्रकटीकरण से छूट प्राप्त है?",
     [("A", "Cabinet papers after a decision is taken",
       "निर्णय लिए जाने के पश्चात मंत्रिमंडल के कागजात"),
      ("B", "Information affecting the sovereignty and integrity of India",
       "भारत की संप्रभुता एवं अखंडता को प्रभावित करने वाली सूचना"),
      ("C", "Annual budget documents", "वार्षिक बजट दस्तावेज़"),
      ("D", "Details of public works contracts", "लोक निर्माण संविदाओं का विवरण")],
     "B"),
    ("gs2.governance.transparency_accountability", 2022, "44",
     "'Citizens charters' are best described as which one of the following?",
     "'नागरिक घोषणापत्र' का निम्नलिखित में से कौन-सा सर्वोत्तम वर्णन है?",
     [("A", "Legally enforceable contracts", "विधिक रूप से प्रवर्तनीय संविदाएँ"),
      ("B", "Statements of service standards without statutory force",
       "सांविधिक बल रहित सेवा मानकों के कथन"),
      ("C", "Constitutional guarantees", "संवैधानिक प्रत्याभूतियाँ"),
      ("D", "Judicial directions", "न्यायिक निर्देश")],
     "B"),
    ("gs2.governance.welfare_schemes", 2021, "56",
     "Direct Benefit Transfer primarily seeks to achieve which one of the following?",
     "प्रत्यक्ष लाभ अंतरण मुख्यतः निम्नलिखित में से किसे प्राप्त करना चाहता है?",
     [("A", "Higher tax collection", "उच्चतर कर संग्रहण"),
      ("B", "Reduction of leakages in subsidy delivery",
       "सब्सिडी प्रदायगी में रिसाव में कमी"),
      ("C", "Increase in customs duty", "सीमा शुल्क में वृद्धि"),
      ("D", "Expansion of the informal sector", "अनौपचारिक क्षेत्र का विस्तार")],
     "B"),
    ("gs2.social_justice.health_education", 2020, "70",
     "The National Health Policy places primary emphasis on which one of the following?",
     "राष्ट्रीय स्वास्थ्य नीति निम्नलिखित में से किस पर प्राथमिक बल देती है?",
     [("A", "Tertiary care hospitals", "तृतीयक देखभाल अस्पताल"),
      ("B", "Comprehensive primary health care", "व्यापक प्राथमिक स्वास्थ्य देखभाल"),
      ("C", "Medical tourism", "चिकित्सा पर्यटन"),
      ("D", "Pharmaceutical exports", "औषधि निर्यात")],
     "B"),
    ("gs2.international_relations.india_neighbourhood", 2019, "83",
     "Which one of the following countries does NOT share a land border with India?",
     "निम्नलिखित में से कौन-सा देश भारत के साथ स्थलीय सीमा साझा नहीं करता है?",
     [("A", "Bhutan", "भूटान"),
      ("B", "Nepal", "नेपाल"),
      ("C", "Sri Lanka", "श्रीलंका"),
      ("D", "Myanmar", "म्याँमार")],
     "C"),
    ("gs2.international_relations.groupings_agreements", 2023, "76",
     "India is a member of all of the following groupings EXCEPT which one?",
     "भारत निम्नलिखित सभी समूहों का सदस्य है, सिवाय किसके?",
     [("A", "BRICS", "ब्रिक्स"),
      ("B", "SCO", "एससीओ"),
      ("C", "ASEAN", "आसियान"),
      ("D", "BIMSTEC", "बिम्सटेक")],
     "C"),
    ("gs2.international_relations.international_institutions", 2024, "88",
     "Which one of the following organisations publishes the 'World Development Report'?",
     "निम्नलिखित में से कौन-सा संगठन 'विश्व विकास रिपोर्ट' प्रकाशित करता है?",
     [("A", "IMF", "आईएमएफ"),
      ("B", "World Bank", "विश्व बैंक"),
      ("C", "WTO", "डब्ल्यूटीओ"),
      ("D", "UNCTAD", "अंकटाड")],
     "B"),
]

# Fabricated A1 analyses — keyed by (topic path, scope)
DEMO_ANALYSES: list[tuple[str, AnalysisScope, str, str, list[dict]]] = [
    ("gs2.constitution.federalism", AnalysisScope.combined,
     "Federalism questions have shifted from textbook Centre-State division towards fiscal "
     "federalism and institutional bargaining. Early framings asked what the Constitution "
     "provides; recent framings ask whether cooperative federalism works in practice, almost "
     "always anchored to a concrete institution — the GST Council, the Finance Commission, or "
     "centrally sponsored schemes. Pure structural questions look exhausted; the live territory "
     "is fiscal devolution and asymmetric arrangements.",
     "संघवाद संबंधी प्रश्न पाठ्यपुस्तकीय केंद्र-राज्य विभाजन से हटकर वित्तीय संघवाद तथा संस्थागत "
     "मोल-भाव की ओर स्थानांतरित हुए हैं। आरंभिक प्रश्न पूछते थे कि संविधान क्या प्रावधान करता है; "
     "हाल के प्रश्न पूछते हैं कि क्या सहकारी संघवाद व्यवहार में कार्य करता है, और वे प्रायः किसी "
     "ठोस संस्था — जीएसटी परिषद, वित्त आयोग, या केंद्र प्रायोजित योजनाओं — से जुड़े होते हैं।",
     [{"angle_en": "Fiscal federalism under the 16th Finance Commission's devolution formula",
       "angle_hi": "16वें वित्त आयोग के हस्तांतरण सूत्र के अंतर्गत वित्तीय संघवाद",
       "rationale_en": "Every Finance Commission cycle since 2015 has produced a question within "
                       "two years of its report."},
      {"angle_en": "Centrally sponsored schemes and the erosion of State fiscal autonomy",
       "angle_hi": "केंद्र प्रायोजित योजनाएँ तथा राज्यों की वित्तीय स्वायत्तता का क्षरण",
       "rationale_en": "Recurring in 2017 and 2020 framings; the underlying tension has not been "
                       "asked directly yet."},
      {"angle_en": "Asymmetric federalism after the reorganisation of Union Territories",
       "angle_hi": "संघ राज्यक्षेत्रों के पुनर्गठन के पश्चात असममित संघवाद",
       "rationale_en": "2024 introduced asymmetry as a framing; it is fresh territory with only "
                       "one prior appearance."}]),
    ("gs2.constitution.basic_structure", AnalysisScope.mains,
     "The basic structure doctrine appears in a stable three-part rotation: its evolution as "
     "judicial innovation, its tension with Article 368, and its application to specific "
     "amendments. Questions almost never ask for the Kesavananda facts; they ask the candidate "
     "to take a position on whether an unelected court should limit an elected Parliament. The "
     "descriptive framing is exhausted; the evaluative one is live.",
     "मूल संरचना सिद्धांत एक स्थिर त्रि-भागीय चक्र में प्रकट होता है: न्यायिक नवाचार के रूप में "
     "इसका विकास, अनुच्छेद 368 के साथ इसका तनाव, तथा विशिष्ट संशोधनों पर इसका अनुप्रयोग। प्रश्न "
     "प्रायः केशवानंद के तथ्य नहीं पूछते; वे अभ्यर्थी से यह मत लेने को कहते हैं कि क्या एक "
     "अनिर्वाचित न्यायालय निर्वाचित संसद को सीमित कर सकता है।",
     [{"angle_en": "Basic structure as a limit on constitutional amendments touching federalism",
       "angle_hi": "संघवाद को स्पर्श करने वाले संविधान संशोधनों पर सीमा के रूप में मूल संरचना",
       "rationale_en": "The doctrine and federalism are each heavily asked but rarely combined."},
      {"angle_en": "Whether secularism as basic structure constrains legislative policy",
       "angle_hi": "क्या मूल संरचना के रूप में पंथनिरपेक्षता विधायी नीति को सीमित करती है",
       "rationale_en": "Named as a basic feature in past answers but never the question's "
                       "subject."}]),
    ("maths1.linear_algebra.eigenvalues_eigenvectors", AnalysisScope.mains,
     "Eigenvalue questions in Paper I are computational first and theoretical second. The "
     "reliable pattern is a small 3x3 matrix requiring the characteristic polynomial, followed by "
     "a Cayley-Hamilton verification or an inverse computed through it. The theory half favours "
     "real symmetric matrices: diagonalisability, reality of eigenvalues, orthogonality of "
     "eigenvectors.",
     "प्रश्नपत्र I में आइगेनमान संबंधी प्रश्न पहले परिकलनात्मक और उसके बाद सैद्धांतिक होते हैं। "
     "विश्वसनीय प्रतिरूप एक छोटा 3x3 आव्यूह है जिसमें अभिलक्षणिक बहुपद अपेक्षित होता है, तत्पश्चात "
     "केली–हैमिल्टन सत्यापन अथवा उसके माध्यम से परिकलित प्रतिलोम।",
     [{"angle_en": "Cayley-Hamilton applied to compute a matrix inverse or a high power",
       "angle_hi": "आव्यूह प्रतिलोम या उच्च घात परिकलित करने हेतु केली–हैमिल्टन का अनुप्रयोग",
       "rationale_en": "Appeared in 2017 and 2023 in near-identical form."},
      {"angle_en": "Orthogonal diagonalisation of a real symmetric matrix with a quadratic form",
       "angle_hi": "द्विघात रूप सहित वास्तविक सममित आव्यूह का लांबिक विकर्णन",
       "rationale_en": "Bridges the eigenvalue and quadratic-forms syllabus headings, which the "
                       "corpus shows are asked together."}]),
]

# Fabricated one-pagers — (topic path, en content, hi content)
DEMO_NOTES: list[tuple[str, dict, dict]] = [
    ("gs2.constitution.federalism",
     {"title": "Indian Federalism — Union–State Relations",
      "overview": "India is a union of states with a strong centre, but the working balance is "
                  "set less by constitutional text than by fiscal institutions and political "
                  "practice. Answers score when they move past the quasi-federal label to a "
                  "named institution.",
      "sections": [
          {"heading": "Anchor facts",
           "points": ["Article 1: India is a 'Union of States' — no right of secession",
                      "Seventh Schedule: Union, State and Concurrent Lists",
                      "Article 280: Finance Commission, constituted every five years",
                      "Article 246A and the GST Council (Article 279A) — shared taxing power",
                      "Article 356: President's rule, narrowed by S.R. Bommai (1994)"]},
          {"heading": "Recurring PYQ angles",
           "points": ["Cooperative vs competitive federalism — aspiration vs practice",
                      "Fiscal devolution and the shrinking divisible pool via cesses",
                      "Centrally sponsored schemes as a constraint on State priorities",
                      "Asymmetric arrangements for special-category and border States"]},
          {"heading": "Common traps",
           "points": ["Listing constitutional articles without evaluating how they work",
                      "Treating 'quasi-federal' as a conclusion rather than a starting point",
                      "Ignoring the GST Council's voting weights when discussing consensus"]}],
      "keywords": ["quasi-federal", "divisible pool", "devolution", "cooperative federalism",
                   "S.R. Bommai", "GST Council", "Inter-State Council", "asymmetric federalism"]},
     {"title": "भारतीय संघवाद — संघ-राज्य संबंध",
      "overview": "भारत सशक्त केंद्र सहित राज्यों का संघ है, किंतु कार्यशील संतुलन संवैधानिक पाठ से "
                  "कम और वित्तीय संस्थाओं तथा राजनीतिक व्यवहार से अधिक निर्धारित होता है। उत्तर तब "
                  "अंक अर्जित करते हैं जब वे 'अर्ध-संघीय' लेबल से आगे बढ़कर किसी नामित संस्था तक "
                  "पहुँचते हैं।",
      "sections": [
          {"heading": "आधारभूत तथ्य",
           "points": ["अनुच्छेद 1: भारत 'राज्यों का संघ' है — पृथक्करण का अधिकार नहीं",
                      "सातवीं अनुसूची: संघ, राज्य एवं समवर्ती सूचियाँ",
                      "अनुच्छेद 280: वित्त आयोग, प्रत्येक पाँच वर्ष में गठित",
                      "अनुच्छेद 246क तथा जीएसटी परिषद (अनुच्छेद 279क) — साझा कराधान शक्ति",
                      "अनुच्छेद 356: राष्ट्रपति शासन, एस.आर. बोम्मई (1994) द्वारा सीमित"]},
          {"heading": "बारंबार आने वाले प्रश्न-कोण",
           "points": ["सहकारी बनाम प्रतिस्पर्धी संघवाद — आकांक्षा बनाम व्यवहार",
                      "वित्तीय हस्तांतरण तथा उपकरों के कारण सिकुड़ता विभाज्य कोष",
                      "राज्यों की प्राथमिकताओं पर बाधा के रूप में केंद्र प्रायोजित योजनाएँ",
                      "विशेष श्रेणी एवं सीमावर्ती राज्यों हेतु असममित व्यवस्थाएँ"]},
          {"heading": "सामान्य भूलें",
           "points": ["अनुच्छेदों की सूची देना किंतु उनके कार्यकरण का मूल्यांकन न करना",
                      "'अर्ध-संघीय' को आरंभ-बिंदु के बजाय निष्कर्ष मान लेना",
                      "सर्वसम्मति की चर्चा करते समय जीएसटी परिषद के मत-भार की उपेक्षा"]}],
      "keywords": ["अर्ध-संघीय", "विभाज्य कोष", "हस्तांतरण", "सहकारी संघवाद", "एस.आर. बोम्मई",
                   "जीएसटी परिषद", "अंतर-राज्य परिषद", "असममित संघवाद"]}),
    ("gs2.polity.parliament",
     {"title": "Parliament — Structure, Oversight and Decline",
      "overview": "Parliament's formal powers are intact while its working oversight has "
                  "weakened: fewer sittings, less committee scrutiny, more ordinances. The "
                  "examinable question is always about the gap between the two.",
      "sections": [
          {"heading": "Anchor facts",
           "points": ["Article 123: ordinance-making power, subject to Parliament's approval",
                      "Article 105: parliamentary privileges",
                      "Financial committees: PAC, Estimates, Committee on Public Undertakings",
                      "Department-related standing committees: 24, reconstituted annually",
                      "Money bill definition: Article 110"]},
          {"heading": "Recurring PYQ angles",
           "points": ["Declining sittings and the quality of legislative scrutiny",
                      "Committees as 'mini-Parliaments' — effectiveness and limits",
                      "Ordinance route and re-promulgation (Krishna Kumar Singh, 2017)",
                      "Anti-defection law and the erosion of individual member voice"]},
          {"heading": "Common traps",
           "points": ["Describing committee types without assessing their output",
                      "Blaming only the executive when procedural rules also matter",
                      "Missing the distinction between money bills and financial bills"]}],
      "keywords": ["ordinance", "standing committee", "Public Accounts Committee", "money bill",
                   "anti-defection", "legislative scrutiny", "guillotine"]},
     {"title": "संसद — संरचना, निगरानी एवं ह्रास",
      "overview": "संसद की औपचारिक शक्तियाँ अक्षुण्ण हैं जबकि उसकी कार्यशील निगरानी कमज़ोर हुई है: "
                  "कम बैठकें, कम समिति-जाँच, अधिक अध्यादेश। परीक्षा-योग्य प्रश्न सदैव इन दोनों के "
                  "बीच के अंतराल के विषय में होता है।",
      "sections": [
          {"heading": "आधारभूत तथ्य",
           "points": ["अनुच्छेद 123: अध्यादेश बनाने की शक्ति, संसद के अनुमोदन के अधीन",
                      "अनुच्छेद 105: संसदीय विशेषाधिकार",
                      "वित्तीय समितियाँ: लोक लेखा, प्राक्कलन, लोक उपक्रम समिति",
                      "विभाग-संबंधित स्थायी समितियाँ: 24, प्रतिवर्ष पुनर्गठित",
                      "धन विधेयक की परिभाषा: अनुच्छेद 110"]},
          {"heading": "बारंबार आने वाले प्रश्न-कोण",
           "points": ["घटती बैठकें तथा विधायी जाँच की गुणवत्ता",
                      "'लघु संसद' के रूप में समितियाँ — प्रभावशीलता एवं सीमाएँ",
                      "अध्यादेश मार्ग एवं पुनःप्रख्यापन (कृष्ण कुमार सिंह, 2017)",
                      "दल-बदल विरोधी कानून तथा सदस्य के व्यक्तिगत स्वर का क्षरण"]},
          {"heading": "सामान्य भूलें",
           "points": ["समितियों के प्रकार बताना किंतु उनके निष्पादन का आकलन न करना",
                      "केवल कार्यपालिका को दोष देना जबकि प्रक्रियात्मक नियम भी महत्वपूर्ण हैं",
                      "धन विधेयक एवं वित्तीय विधेयक के अंतर की उपेक्षा"]}],
      "keywords": ["अध्यादेश", "स्थायी समिति", "लोक लेखा समिति", "धन विधेयक", "दल-बदल",
                   "विधायी जाँच"]}),
]


# --- seeding -----------------------------------------------------------------


async def topic_ids_by_path(session: AsyncSession) -> dict[str, int]:
    rows = (await session.execute(select(Topic.path, Topic.id))).all()
    return {str(path): tid for path, tid in rows}


async def paper_by_code(session: AsyncSession, code: str) -> Paper:
    paper = (
        await session.execute(select(Paper).where(Paper.code == code))
    ).scalar_one_or_none()
    if paper is None:
        raise SystemExit(
            f"Paper {code!r} not found — run scripts/seed_taxonomy.py first."
        )
    return paper


async def wipe_demo(session: AsyncSession) -> int:
    """Remove every demo row: questions marked session='demo', their children,
    and the analyses/notes/scans created alongside them."""
    q_ids = list(
        (
            await session.execute(
                select(Question.id).where(Question.session == DEMO_SESSION)
            )
        ).scalars()
    )
    if q_ids:
        await session.execute(
            delete(QuestionEmbedding).where(QuestionEmbedding.question_id.in_(q_ids))
        )
        await session.execute(
            delete(QuestionTopicMap).where(QuestionTopicMap.question_id.in_(q_ids))
        )
        await session.execute(delete(QuestionOption).where(QuestionOption.question_id.in_(q_ids)))
        await session.execute(delete(Question).where(Question.id.in_(q_ids)))

    await session.execute(delete(TopicAnalysis).where(TopicAnalysis.prompt_ref.like("demo/%")))
    await session.execute(delete(TopicNote).where(TopicNote.prompt_ref.like("demo/%")))
    await session.execute(delete(SourceScan).where(SourceScan.r2_key.like("demo/%")))
    await session.flush()
    return len(q_ids)


async def demo_scan(session: AsyncSession, paper: Paper, year: int) -> SourceScan:
    scan = SourceScan(
        exam_id=paper.exam_id,
        paper_id=paper.id,
        year=year,
        r2_key=f"demo/{paper.code}-{year}.pdf",
        ocr_status=OcrStatus.published,
        ocr_confidence=1.0,
        reviewed_by="seed_demo_questions.py",
    )
    session.add(scan)
    await session.flush()
    return scan


async def seed(session: AsyncSession) -> dict[str, int]:
    topics = await topic_ids_by_path(session)
    counts = {"questions": 0, "options": 0, "analyses": 0, "notes": 0}
    scans: dict[tuple[int, int], SourceScan] = {}

    async def scan_for(paper: Paper, year: int) -> SourceScan:
        key = (paper.id, year)
        if key not in scans:
            scans[key] = await demo_scan(session, paper, year)
        return scans[key]

    def topic_id(path: str) -> int:
        if path not in topics:
            raise SystemExit(
                f"Topic path {path!r} not in the taxonomy — re-run seed_taxonomy.py "
                "or fix the demo corpus."
            )
        return topics[path]

    gs2 = await paper_by_code(session, "mains-gs2")
    maths1 = await paper_by_code(session, "mains-maths-1")
    prelims = await paper_by_code(session, "prelims-gs1")

    created: list[Question] = []

    for path, year, number, marks, text_en, text_hi in MAINS_GS2:
        scan = await scan_for(gs2, year)
        q = Question(
            exam_id=gs2.exam_id, paper_id=gs2.id, year=year, session=DEMO_SESSION,
            question_number=number, marks=marks, language=QuestionLanguage.bilingual,
            question_text_en=text_en, question_text_hi=text_hi,
            source_scan_id=scan.id, status=QuestionStatus.published,
        )
        session.add(q)
        await session.flush()
        session.add(
            QuestionTopicMap(question_id=q.id, topic_id=topic_id(path),
                             confidence=0.95, tagged_by=TaggedBy.human)
        )
        created.append(q)

    for path, year, number, marks, text_en, text_hi, latex in MAINS_MATHS:
        scan = await scan_for(maths1, year)
        q = Question(
            exam_id=maths1.exam_id, paper_id=maths1.id, year=year, session=DEMO_SESSION,
            question_number=number, marks=marks, language=QuestionLanguage.bilingual,
            question_text_en=text_en, question_text_hi=text_hi, math_notation_latex=latex,
            source_scan_id=scan.id, status=QuestionStatus.published,
        )
        session.add(q)
        await session.flush()
        session.add(
            QuestionTopicMap(question_id=q.id, topic_id=topic_id(path),
                             confidence=0.95, tagged_by=TaggedBy.human)
        )
        created.append(q)

    for path, year, number, text_en, text_hi, options, correct in PRELIMS_GS1:
        scan = await scan_for(prelims, year)
        q = Question(
            exam_id=prelims.exam_id, paper_id=prelims.id, year=year, session=DEMO_SESSION,
            question_number=number, marks=2.0, language=QuestionLanguage.bilingual,
            question_text_en=text_en, question_text_hi=text_hi,
            source_scan_id=scan.id, status=QuestionStatus.published,
        )
        session.add(q)
        await session.flush()
        for label, opt_en, opt_hi in options:
            session.add(
                QuestionOption(
                    question_id=q.id, option_label=label,
                    option_text_en=opt_en, option_text_hi=opt_hi,
                    # Real correctness only ever comes from an official answer key
                    # (scripts/load_answer_key.py); this is a fabricated demo key.
                    is_correct=(label == correct),
                )
            )
            counts["options"] += 1
        session.add(
            QuestionTopicMap(question_id=q.id, topic_id=topic_id(path),
                             confidence=0.95, tagged_by=TaggedBy.human)
        )
        created.append(q)

    counts["questions"] = len(created)

    for path, scope, summary_en, summary_hi, angles in DEMO_ANALYSES:
        tid = topic_id(path)
        corpus = (
            sum(1 for p, *_ in MAINS_GS2 if p == path)
            + sum(1 for p, *_ in MAINS_MATHS if p == path)
            + sum(1 for p, *_ in PRELIMS_GS1 if p == path)
        )
        session.add(
            TopicAnalysis(
                topic_id=tid, scope=scope, model_name="demo-fixture",
                prompt_ref="demo/seed_demo_questions.py", question_count=corpus,
                pattern_summary_en=summary_en, pattern_summary_hi=summary_hi,
                predicted_angles=angles,
                prediction_outcomes={"hits": 2, "misses": 1, "checked_years": [2024]},
            )
        )
        counts["analyses"] += 1

    for path, content_en, content_hi in DEMO_NOTES:
        tid = topic_id(path)
        corpus = sum(1 for p, *_ in MAINS_GS2 if p == path)
        session.add(
            TopicNote(
                topic_id=tid, version=1, model_name="demo-fixture",
                prompt_ref="demo/seed_demo_questions.py", question_count=corpus,
                content_en=content_en, content_hi=content_hi,
                status=TopicNoteStatus.published,
            )
        )
        counts["notes"] += 1

    await session.flush()
    await embed_all(session, created)
    return counts


async def embed_all(session: AsyncSession, questions: list[Question]) -> None:
    """Embed the demo corpus with whichever provider is configured, so /search
    works. Without a Voyage key this is the dev hashing stand-in — lexical only."""
    provider = get_embedding_provider()
    variants: list[tuple[int, str, str]] = []
    for q in questions:
        for lang, text in (("en", q.question_text_en), ("hi", q.question_text_hi)):
            if text:
                full = f"{text}\n{q.math_notation_latex}" if q.math_notation_latex else text
                variants.append((q.id, lang, full))

    vectors, usage = await provider.embed([t for _, _, t in variants], input_type="document")
    await record_usage(
        session, feature=LlmFeature.embedding, usage=usage,
        related_entity_type="demo_seed",
    )
    for (qid, lang, _), vector in zip(variants, vectors, strict=True):
        session.add(
            QuestionEmbedding(
                question_id=qid, lang=lang, embedding=vector,
                embedding_model=provider.model_name,
            )
        )
    print(f"  embedded {len(variants)} language variants with {provider.model_name}")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wipe", action="store_true",
                        help="remove demo rows and exit without reseeding")
    args = parser.parse_args()

    settings = get_settings()
    if settings.env != "dev":
        raise SystemExit(
            f"Refusing to seed fabricated questions in env={settings.env!r}. "
            "This script is dev-only."
        )

    async with async_session_factory() as session:
        removed = await wipe_demo(session)
        if removed:
            print(f"Removed {removed} existing demo questions")
        if args.wipe:
            await session.commit()
            print("Demo data wiped.")
            return

        counts = await seed(session)
        await session.commit()

    print(
        f"Seeded {counts['questions']} DEMO questions "
        f"({counts['options']} MCQ options), {counts['analyses']} analyses, "
        f"{counts['notes']} one-pagers."
    )
    print(
        "\n  These are FABRICATED placeholders, not real UPSC questions.\n"
        "  Remove them before showing anything to a user:\n"
        "      uv run python scripts/seed_demo_questions.py --wipe"
    )


if __name__ == "__main__":
    asyncio.run(main())
