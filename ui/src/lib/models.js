import model_1r1c from '@data/examples/chambre_1r1c.json';
import model_2r2c from '@data/examples/chambre_2r2c.json';
import model_v1   from '@data/examples/chambre_v1.json';

/** @type {{ id: string, label: string, model: import('./types').ThermalModel }[]} */
export const MODELS = [
	{ id: 'chambre_1r1c', label: '1R1C — mur simplifié', model: model_1r1c },
	{ id: 'chambre_2r2c', label: '2R2C — masse du mur', model: model_2r2c },
	{ id: 'chambre_v1',   label: 'V1 — modèle physique', model: model_v1 }
];
