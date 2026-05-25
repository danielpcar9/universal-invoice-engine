import uuid
from decimal import Decimal
from datetime import date
from typing import Optional

from lxml import etree  # type: ignore


class SepaGenerationError(Exception):
    pass


class SepaGenerator:
    """
    Generates ISO 20022 pain.001.001.03 (CustomerCreditTransferInitiation)
    for SEPA credit transfers.
    """

    NSMAP = {
        None: "urn:iso:std:iso:20022:tech:xsd:pain.001.001.03",
    }

    @classmethod
    def generate(
        cls,
        *,
        message_id: str,
        creation_date_time: str,
        initiating_party_name: str,
        payment_info_id: str,
        requested_execution_date: date,
        debtor_name: str,
        debtor_iban: str,
        debtor_bic: Optional[str],
        creditor_name: str,
        creditor_iban: str,
        creditor_bic: Optional[str],
        amount: Decimal,
        currency: str = "EUR",
        end_to_end_id: Optional[str] = None,
        charge_bearer: str = "SLEV",
    ) -> bytes:
        """
        Returns the XML as UTF-8 bytes.
        """
        if amount <= 0:
            raise SepaGenerationError("Amount must be positive")

        if currency != "EUR":
            raise SepaGenerationError("Only EUR is supported for SEPA")

        e2e_id = end_to_end_id or str(uuid.uuid4())

        # ── Root ──
        root = etree.Element("Document", nsmap=cls.NSMAP)
        ccti = etree.SubElement(root, "CstmrCdtTrfInitn")

        # ── Group Header ──
        grp_hdr = etree.SubElement(ccti, "GrpHdr")
        etree.SubElement(grp_hdr, "MsgId").text = message_id
        etree.SubElement(grp_hdr, "CreDtTm").text = creation_date_time
        etree.SubElement(grp_hdr, "NbOfTxs").text = "1"
        etree.SubElement(grp_hdr, "CtrlSum").text = f"{amount:.2f}"

        initg_pty = etree.SubElement(grp_hdr, "InitgPty")
        etree.SubElement(initg_pty, "Nm").text = initiating_party_name

        # ── Payment Information ──
        pmt_inf = etree.SubElement(ccti, "PmtInf")
        etree.SubElement(pmt_inf, "PmtInfId").text = payment_info_id
        etree.SubElement(pmt_inf, "PmtMtd").text = "TRF"
        etree.SubElement(pmt_inf, "BtchBookg").text = "true"
        etree.SubElement(pmt_inf, "NbOfTxs").text = "1"
        etree.SubElement(pmt_inf, "CtrlSum").text = f"{amount:.2f}"

        pmt_tp_inf = etree.SubElement(pmt_inf, "PmtTpInf")
        svc_lvl = etree.SubElement(pmt_tp_inf, "SvcLvl")
        etree.SubElement(svc_lvl, "Cd").text = "SEPA"

        etree.SubElement(pmt_inf, "ReqdExctnDt").text = requested_execution_date.isoformat()

        # Debtor
        dbtr = etree.SubElement(pmt_inf, "Dbtr")
        etree.SubElement(dbtr, "Nm").text = debtor_name

        dbtr_acct = etree.SubElement(pmt_inf, "DbtrAcct")
        dbtr_acct_id = etree.SubElement(dbtr_acct, "Id")
        etree.SubElement(dbtr_acct_id, "IBAN").text = debtor_iban

        if debtor_bic:
            dbtr_agt = etree.SubElement(pmt_inf, "DbtrAgt")
            fin_instn_id = etree.SubElement(dbtr_agt, "FinInstnId")
            etree.SubElement(fin_instn_id, "BIC").text = debtor_bic

        etree.SubElement(pmt_inf, "ChrgBr").text = charge_bearer

        # ── Credit Transfer Transaction Information ──
        cdt_trf_tx_inf = etree.SubElement(pmt_inf, "CdtTrfTxInf")

        pmt_id = etree.SubElement(cdt_trf_tx_inf, "PmtId")
        etree.SubElement(pmt_id, "EndToEndId").text = e2e_id

        amt = etree.SubElement(cdt_trf_tx_inf, "Amt")
        instd_amt = etree.SubElement(amt, "InstdAmt", Ccy=currency)
        instd_amt.text = f"{amount:.2f}"

        if creditor_bic:
            cdtr_agt = etree.SubElement(cdt_trf_tx_inf, "CdtrAgt")
            fin_instn_id_c = etree.SubElement(cdtr_agt, "FinInstnId")
            etree.SubElement(fin_instn_id_c, "BIC").text = creditor_bic

        cdtr = etree.SubElement(cdt_trf_tx_inf, "Cdtr")
        etree.SubElement(cdtr, "Nm").text = creditor_name

        cdtr_acct = etree.SubElement(cdt_trf_tx_inf, "CdtrAcct")
        cdtr_acct_id = etree.SubElement(cdtr_acct, "Id")
        etree.SubElement(cdtr_acct_id, "IBAN").text = creditor_iban

        # Serialize
        xml_bytes = etree.tostring(
            root,
            pretty_print=True,
            xml_declaration=True,
            encoding="UTF-8",
        )
        return xml_bytes