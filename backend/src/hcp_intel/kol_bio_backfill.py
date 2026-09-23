"""One-time backfill: regenerate KOL.bio for all 39 live KOLs.

Original bios were short one-liners entered manually with no institutional
sourcing. Replaced with fresh, original paraphrases written from each
doctor's real institutional bio page (hospital "meet the doctor" prose is
copyrighted, so this is a paraphrase from facts, not a copy), or from
confirmed institution/title/specialty facts where no narrative bio existed
anywhere (~15 of the 39). Sourcing detail for each entry lives outside this
repo in the research notes that produced BIO_TEXT below.

Run once, manually, against a real environment:

    python -m hcp_intel.kol_bio_backfill

Skips any KOL whose slug isn't in BIO_TEXT (nothing to do) and any KOL
where `bio` is already curated by a human via the admin API AND already
matches BIO_TEXT (idempotent re-run). Does not touch institution, title,
or photo_url — those were already backfilled directly via the admin API.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import async_session_maker
from models.kol import KOL
from services.kol_write import apply_kol_field_update

log = logging.getLogger(__name__)

BIO_TEXT: dict[str, str] = {
    "brufsky": "Dr. Adam Brufsky is a Professor of Medicine and Associate Chief of the Division of Hematology/Oncology at the University of Pittsburgh and UPMC Hillman Cancer Center, where he also directs the Comprehensive Breast Cancer Center. His research centers on new clinical therapeutics for breast cancer and the biological interactions between bone and breast cancer, with a particular focus on bone health in metastatic HR-positive disease.",
    "bardia": "Dr. Aditya Bardia is a Professor of Medicine at UCLA Health's Jonsson Comprehensive Cancer Center, where he directs the Breast Cancer Program. An internationally recognized leader in cancer therapeutics, he has been a principal investigator on trials behind sacituzumab govitecan and elacestrant, and his work on blood-based biomarkers has helped shape how clinicians track and understand treatment resistance.",
    "conlin": "Dr. Alison Conlin is a medical oncologist with the Providence Cancer Institute in Portland, Oregon, where she leads the breast cancer program in medical oncology. She is known for her work on early- and advanced-stage breast cancer, with a particular interest in bringing new drugs and clinical trial access to patients facing metastatic disease and brain metastases.",
    "krie": "Dr. Amy Krie is Clinical Director of the Avera Breast Center in Sioux Falls, South Dakota, part of the Avera Cancer Institute. She focuses on bringing individualized, interdisciplinary breast cancer care to patients across the Dakotas, combining precision medicine and genomic testing with a personal understanding of what a breast cancer diagnosis means for a patient balancing career and family.",
    "garrido-castro": "Dr. Ana Garrido-Castro is Director of Triple-Negative Breast Cancer Research in the Division of Breast Oncology at Dana-Farber Cancer Institute and an Assistant Professor of Medicine at Harvard Medical School. Her research develops new therapeutic strategies for breast cancer, with particular emphasis on immunotherapy and antibody-drug conjugates for triple-negative disease, work recognized with the 2023 Conquer Cancer-Triple Negative Breast Cancer Foundation Advanced Clinical Research Award.",
    "odea": "Dr. Anne O'Dea is Medical Director of the Breast Cancer Survivorship Program at the University of Kansas Medical Center and KU Cancer Center. A dedicated regional voice for rural oncology care, she built a rural cancer practice and leads survivorship research aimed at improving quality of life and clinical trial access for cancer survivors outside major metro areas.",
    "tweed": "Dr. Carol Tweed is a physician at Maryland Oncology Hematology in Annapolis, treating a broad range of hematologic and oncologic disorders with a focus on breast cancer. A graduate of Duke University and Washington University in St. Louis, she was formerly on faculty at the University of Pennsylvania's Abramson Cancer Center before relocating to Maryland, where she co-founded the Maryland Breast Cancer Consortium and serves as a national speaker on breast cancer care.",
    "hamilton": "Dr. Erika Hamilton is a board-certified medical oncologist with SCRI Oncology Partners and Director of Breast Cancer Research at Sarah Cannon Research Institute. As the daughter of a breast cancer survivor, she brings a personal understanding of compassionate, individualized care to her research leadership roles within ASCO and ESMO.",
    "yan": "Dr. Fengting Yan is a Clinical Associate Professor in the Clinical Research Division at Fred Hutch Cancer Center and in the Division of Hematology/Oncology at the University of Washington School of Medicine. Trained first in obstetrics and gynecology in China before pursuing internal medicine and hematology-oncology in the U.S., she treats breast and ovarian cancer and describes bringing the same compassion to her patients that she'd want for her own family.",
    "moscol": "Dr. Giancarlo Moscol is an Associate Professor of Breast Medical Oncology at MD Anderson Cancer Center's The Woodlands campus, where he has led the Breast Medical Oncology Tumor Board since 2018. He focuses on personalized medical oncology paired with a high-satisfaction approach to clinical care.",
    "vidal": "Dr. Gregory Vidal is a medical oncologist at West Cancer Center & Research Institute and Regional One Health in Memphis, and an Associate Professor at the University of Tennessee Health Science Center. He directs clinical research at West Cancer Center, chairs OneOncology's national Breast Cancer Program, and lectures internationally on breast cancer care and health equity.",
    "mcarthur": "Dr. Heather McArthur is Clinical Director of the Breast Cancer Program at UT Southwestern's Simmons Comprehensive Cancer Center, where she holds the Komen Distinguished Chair in Clinical Breast Cancer Research. She trained in Canada before an advanced fellowship at Memorial Sloan Kettering, where she helped build the institution's breast cancer immunotherapy program, and later led breast oncology at Cedars-Sinai before joining UT Southwestern in 2021.",
    "rugo": "Dr. Hope Rugo is Chief of Breast Medical Oncology and Director of the Women's Cancers Program at City of Hope, a role she took on in 2025 after 35 years on faculty at UCSF. A globally recognized authority on triple-negative breast cancer and clinical trial safety, she continues to shape how the field balances efficacy with quality of life for patients in trials.",
    "krop": "Dr. Ian Krop is Section Chief of Medical Oncology and Hematology and Deputy Director for Clinical Affairs at Yale Cancer Center and Smilow Cancer Hospital, following years as the center's Chief Clinical Research Officer. His research on HER2-positive breast cancer has helped shape the approval of nearly every major HER2-targeted therapy developed over the past fifteen years.",
    "makhlin": "Dr. Igor Makhlin is an Assistant Professor of Clinical Medicine in Hematology-Oncology at Penn Medicine's Abramson Cancer Center, where his clinical and academic work is based at the Rena Rowan Breast Center. He treats adult patients across the spectrum of hematologic and oncologic breast disease.",
    "kang": "Dr. Irene Kang is Medical Director of Women's Health Medical Oncology at City of Hope Orange County, where she also holds an academic appointment in the Department of Medical Oncology and Therapeutics Research. Her work centers on molecular profiling and improving long-term survivorship and toxicity management for breast cancer patients.",
    "mouabbi": "Dr. Jason Mouabbi is an Assistant Professor of Breast Medical Oncology at MD Anderson Cancer Center. His research is dedicated almost exclusively to invasive lobular carcinoma, a distinct and understudied form of breast cancer, and to using circulating tumor DNA for treatment surveillance.",
    "oshaughnessy": "Dr. Joyce O'Shaughnessy co-chairs Breast Cancer Research and chairs Breast Cancer Prevention Research at Baylor-Sammons Cancer Center and Texas Oncology, part of the US Oncology Network, where she also serves on the Scientific Advisory Board for US Oncology Research. She is one of the most widely recognized educators in oncology, with a particular focus on high-risk triple-negative breast cancer.",
    "mccann": "Dr. Kelly McCann is an Associate Professor in the Division of Medical Oncology at UC San Diego Moores Cancer Center, having recently joined UCSD after a period at UCLA. A physician-scientist trained in the Slamon Lab, her research focuses on DNA repair pathways and PARP inhibitors in breast cancer.",
    "jhaveri": "Dr. Komal Jhaveri is Section Head of the Endocrine Therapy Research Program and Clinical Director of the Early Drug Development Service at Memorial Sloan Kettering Cancer Center, and an Associate Professor of Medicine at Weill Cornell Medicine. She cares for hundreds of breast cancer patients each year while researching how PI3K/Akt/mTOR pathway biology drives resistance to hormone-receptor-positive treatments.",
    "mardones": "Dr. Mabel Mardones is a board-certified medical oncologist and hematologist and Partner at Rocky Mountain Cancer Centers in Colorado, with advanced sub-specialty expertise across all breast cancer subtypes. She uses genomic testing to personalize therapy for each patient, following NCCN guidelines, and serves on SCRI's Executive Committee for Breast Cancer Research.",
    "pegram": "Dr. Mark Pegram holds the Suzy Yuan-Huey Hung Endowed Professorship in Medical Oncology at Stanford and serves as Associate Director of Clinical Research at the Stanford Comprehensive Cancer Institute, a role he has held since 2013. A foundational figure in HER2-targeted therapy, his research was instrumental in the development and approval of Herceptin.",
    "robson": "Dr. Mark Robson is Chief of the Breast Medicine Service at Memorial Sloan Kettering Cancer Center and a Professor of Medicine at Weill Cornell Medical College. He specializes in identifying and managing inherited cancer risk, particularly BRCA1 and BRCA2 mutations, and has helped pioneer the use of PARP inhibitors in hereditary breast cancer.",
    "dietrich": "Dr. Martin Dietrich is a medical oncologist at Cancer Care Centers of Brevard in Florida and an Assistant Professor of Internal Medicine at the University of Central Florida. He holds dual doctorates in cancer biology and molecular genetics, and his clinical philosophy centers on matching therapy to each tumor's individual molecular biology.",
    "lustberg": "Dr. Maryam Lustberg directs the Center for Breast Cancer at Smilow Cancer Hospital and chairs Breast Medical Oncology at Yale Cancer Center. A recognized world expert in supportive care, she focuses her research on reducing the toxicity of cancer treatment and improving patient-reported outcomes, building on a career shaped by watching physicians form lasting, trusted relationships with cancer patients.",
    "kruse": "Dr. Megan Kruse is Director of Breast Medical Oncology and Co-Leader of the Breast Cancer Program at Cleveland Clinic. She is a leading expert in invasive lobular carcinoma and in using circulating tumor DNA to personalize treatment monitoring for breast cancer patients.",
    "cairo": "Dr. Michelina Cairo is a medical oncologist with Texas Oncology, practicing at the Memorial Hermann Memorial City campus in Houston. During her fellowship she completed a dedicated breast cancer research track and additional training in breast cancer and sarcoma at MD Anderson, and her commitment to health education has taken her from teen health programs in New Haven to women's health research in Senegal.",
    "rimawi": "Dr. Mothaffar Rimawi is Executive Medical Director of the Dan L Duncan Comprehensive Cancer Center at Baylor College of Medicine, where he is a Professor of Medicine. His work translates laboratory research into new breast cancer treatments and back again, with contributions central to advances in HER2-positive treatment optimization, endocrine therapy, and targeted therapy for triple-negative disease.",
    "iyengar": "Dr. Neil Iyengar is Director of Survivorship Services and Co-Director of the Breast Medical Oncology Program at Winship Cancer Institute of Emory University, which he joined in 2025 after nearly fifteen years at Memorial Sloan Kettering. A pioneer in what he calls 'Metabolic Oncology,' his research examines how metabolic health and exercise biology influence tumor growth and long-term survivorship.",
    "bagegni": "Dr. Nusayba Bagegni is an Associate Professor of Medicine and Associate Medical Director of Clinical Research at Washington University School of Medicine and Siteman Cancer Center in St. Louis. A 2024 NCI Early Career Cancer Clinical Investigator Award recipient, she specializes in aggressive breast cancer subtypes and leads breast cancer clinical trials for the division.",
    "tarantino": "Dr. Paolo Tarantino is an Advanced Research Fellow in the Breast Oncology Program at Dana-Farber Cancer Institute and Harvard Medical School. Internationally recognized for his work defining 'HER2-low' and 'ultralow' tumor biology, he focuses his research on antibody-drug conjugate sequencing and directions for HER2-positive metastatic breast cancer.",
    "callahan": "Dr. Rena Callahan is a board-certified hematologist and medical oncologist at UCLA Health, practicing in Santa Monica and Santa Clarita, whose practice is dedicated exclusively to breast cancer care. An Associate Clinical Professor at the David Geffen School of Medicine at UCLA, she integrates genomic profiling and biomarker-driven approaches into an individualized, collaborative model of care.",
    "birhiray": "Dr. Ruemu Birhiray is an Attending Physician at Hematology Oncology of Indiana and a Professor of Clinical Medicine at Marian University College of Osteopathic Medicine. Before joining HOI in 2001, he directed the bone marrow transplant program at Marshfield Cancer Center in Wisconsin, and his research spans immunotherapy, lymphoma, and bone marrow transplantation.",
    "rao": "Dr. Ruta Rao is Medical Director of the Rush University Cancer Center and Director of the Coleman Comprehensive Breast Clinic, where she has practiced since joining as a fellow in 2002. Her clinical and research focus is breast cancer, and she serves as principal investigator on multiple clinical trials exploring new treatment approaches.",
    "modi": "Dr. Shanu Modi is a medical oncologist at Memorial Sloan Kettering Cancer Center whose clinical practice is devoted solely to breast cancer, and an Associate Professor of Medicine at Weill Cornell Medicine. As lead investigator of the DESTINY-Breast04 trial, her work was foundational to the discovery and approval of Enhertu and to establishing 'HER2-low' as a new treatable category.",
    "ballinger": "Dr. Tarah Ballinger is an Associate Professor of Clinical Medicine at Indiana University and the Vera Bradley Foundation Scholar in Breast Cancer Research at the IU Simon Cancer Center. Her research examines how body composition and physical activity shape outcomes across the cancer continuum, from prevention through late-stage disease, through her practice with the Catherine Peachey Prevention Program.",
    "traina": "Dr. Tiffany Traina is Vice Chair of Outpatient Operations in the Department of Medicine at Memorial Sloan Kettering Cancer Center and an Associate Professor at Weill Cornell Medical College. A global authority on triple-negative breast cancer, she leads early-phase trials of novel therapeutics and antibody-drug conjugates as head of MSK's TNBC Clinical Research Program.",
    "gadi": "Dr. VK Gadi is Deputy Director of the University of Illinois Cancer Center and Professor and Director of Medical Oncology at UIC College of Medicine, which he joined in 2020 after twenty years in Seattle at the University of Washington and Fred Hutchinson Cancer Center. A physician-scientist and nationally recognized breast cancer expert, he has worked to expand and diversify Chicago's solid-tumor research and clinical workforce.",
    "gradishar": "Dr. William Gradishar is the Betsy Bramsen Professor of Breast Oncology and Deputy Director of the Robert H. Lurie Comprehensive Cancer Center at Northwestern Medicine, where he also directs the Maggie Daley Center for Women's Cancer Care. As chair of the NCCN Breast Cancer Guidelines Panel, his work has long helped define the national standard of care in breast oncology.",
}


async def _apply(session: AsyncSession) -> dict[str, list[str]]:
    results: dict[str, list[str]] = {}
    rows = (
        await session.execute(select(KOL).where(KOL.slug.in_(BIO_TEXT.keys())))
    ).scalars().all()
    by_slug = {kol.slug: kol for kol in rows}

    for slug, bio in BIO_TEXT.items():
        kol = by_slug.get(slug)
        if kol is None:
            log.warning("kol_bio_backfill: no KOL row for slug=%s, skipping", slug)
            continue
        changed = apply_kol_field_update(kol, {"bio": bio}, source="admin")
        results[slug] = changed

    return results


async def run(session: AsyncSession | None = None) -> dict[str, list[str]]:
    """Apply BIO_TEXT to every matching KOL. Returns {slug: changed_fields}.

    Pass `session` in tests to reuse the caller's transaction-scoped fixture
    session instead of opening a new connection via `async_session_maker` —
    keeps writes inside the fixture's rollback boundary instead of committing
    directly to the shared test database.
    """
    if session is not None:
        return await _apply(session)

    async with async_session_maker() as owned_session:
        results = await _apply(owned_session)
        await owned_session.commit()
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    outcome = asyncio.run(run())
    changed_count = sum(1 for v in outcome.values() if v)
    log.info(
        "kol_bio_backfill complete: %d/%d KOLs updated", changed_count, len(outcome)
    )
