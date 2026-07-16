# Copyright 2026      Louis Héraut <louis.heraut@inrae.fr>*1
#
# *1 INRAE, UR RiverLy, Villeurbanne, France
#
# This file is part of the card-api service.
#
# card-api is free software: you can redistribute it and/or modify it
# under the terms of the license in the LICENSE file of this repository.

"""Sérialisation des DataFrames vers le JSON de l'API (partagée entre
les endpoints synchrones et les jobs)."""

import math

import pandas as pd


def clean(records):
    """NaN -> null pour le JSON."""
    return [{k: (None if isinstance(v, float) and math.isnan(v) else v)
             for k, v in r.items()} for r in records]


def serialize(df, orient="records"):
    """records (défaut, style Hub'Eau) ou columns (colonnaire, compact,
    rechargeable en DataFrame d'une ligne)."""
    out = df.copy()
    for c in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[c]):
            out[c] = out[c].dt.strftime("%Y-%m-%d")
    out = out.astype(object).where(out.notna(), None)
    if orient == "columns":
        return {c: out[c].tolist() for c in out.columns}
    return clean(out.to_dict(orient="records"))
