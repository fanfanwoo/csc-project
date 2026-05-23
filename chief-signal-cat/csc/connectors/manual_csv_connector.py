from csc.schemas.items import RawItem

# Stub — for manually curated signal inputs. Implement when CSV intake is needed.


def fetch_csv(source_cfg: dict) -> list[RawItem]:
    raise NotImplementedError("manual_csv_connector not yet implemented")
