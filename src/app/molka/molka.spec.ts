import { ComponentFixture, TestBed } from '@angular/core/testing';

import { Molka } from './molka';

describe('Molka', () => {
  let component: Molka;
  let fixture: ComponentFixture<Molka>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [Molka],
    }).compileComponents();

    fixture = TestBed.createComponent(Molka);
    component = fixture.componentInstance;
    await fixture.whenStable();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
