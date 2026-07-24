import os
import json
import unittest

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
CONCEPT_MAP_PATH = os.path.join(BASE_DIR, 'storage', 'kice_math_concept_map.json')
GLOSSARY_PATH = os.path.join(BASE_DIR, 'docs', 'Korean_Math_Glossary.json')

class TestConceptMapAndGlossary(unittest.TestCase):
    def test_concept_map_structure(self):
        self.assertTrue(os.path.exists(CONCEPT_MAP_PATH), "kice_math_concept_map.json missing")
        with open(CONCEPT_MAP_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        self.assertIn("concepts", data)
        self.assertGreater(len(data["concepts"]), 0)
        
        for concept in data["concepts"]:
            self.assertIn("concept_id", concept)
            self.assertIn("concept_name_english", concept)
            self.assertIn("latex_trigger_patterns", concept)
            self.assertIn("academic_definition", concept)

    def test_korean_math_glossary_structure(self):
        self.assertTrue(os.path.exists(GLOSSARY_PATH), "Korean_Math_Glossary.json missing")
        with open(GLOSSARY_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        self.assertIn("curriculum_terms", data)
        self.assertIn("condition_terms", data)
        self.assertIn("heuristics_terms", data)
        self.assertEqual(data["curriculum_terms"]["수학I"], "Algebra")

if __name__ == '__main__':
    unittest.main()
