#!/bin/bash

# Instalar Demucs directamente desde pip
pip install -U demucs

# Descargar modelo por defecto de Demucs (htdemucs)
python3 -m demucs --dl
