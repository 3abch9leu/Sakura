import { Component, signal } from '@angular/core';
import { molkaComponent } from './molka/molka';

@Component({
  selector: 'app-root',
  imports: [molkaComponent],
  templateUrl: './app.html',
  styleUrl: './app.css'
})
export class App {
  protected readonly title = signal('camera');
}
